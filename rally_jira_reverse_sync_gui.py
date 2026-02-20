#!/usr/bin/env python3
"""
Rally to Jira Reverse Sync GUI
Fetches Rally items and updates their status based on matching Jira issues
"""

import tkinter as tk
from tkinter import ttk, messagebox, filedialog, scrolledtext
from tkinter.font import Font
import json
import os
import threading
import time
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Import sync libraries
try:
    from jira import JIRA
    from pyral import Rally, rallyWorkset
    import requests
    from dotenv import load_dotenv
    import re  # For pattern matching JIRA keys in Rally names
except ImportError as e:
    messagebox.showerror("Import Error", 
                        f"Required libraries not found: {e}\n\n"
                        "Please run: pip install -r requirements.txt")
    exit(1)

# Default status mappings (Jira -> Rally)
DEFAULT_STATUS_MAPPINGS = {
    "To Do": "Defined",
    "In Progress": "In-Progress", 
    "Code Review": "In-Progress",
    "Testing": "Completed",
    "Done": "Accepted",
    "Closed": "Accepted",
    "Open": "Defined",
    "Resolved": "Completed"
}

class SyncCheckpointManager:
    """Manages checkpoint/state persistence for sync operations to enable resuming"""
    
    def __init__(self, workspace_dir: str = None):
        self.workspace_dir = workspace_dir or os.getcwd()
        self.checkpoint_dir = os.path.join(self.workspace_dir, "sync_checkpoints")
        self.ensure_checkpoint_dir()
    
    def ensure_checkpoint_dir(self):
        """Ensure checkpoint directory exists"""
        if not os.path.exists(self.checkpoint_dir):
            os.makedirs(self.checkpoint_dir)
    
    def get_checkpoint_file(self, sync_config: dict) -> str:
        """Generate checkpoint filename based on sync configuration"""
        config_hash = hash(json.dumps(sorted(sync_config.items())))
        return os.path.join(self.checkpoint_dir, f"sync_checkpoint_{abs(config_hash)}.json")
    
    def save_checkpoint(self, sync_config: dict, checkpoint_data: dict):
        """Save checkpoint data to file"""
        try:
            checkpoint_file = self.get_checkpoint_file(sync_config)
            checkpoint_data['last_updated'] = datetime.now().isoformat()
            checkpoint_data['sync_config'] = sync_config
            
            with open(checkpoint_file, 'w', encoding='utf-8') as f:
                json.dump(checkpoint_data, f, indent=2)
            
            return True, f"Checkpoint saved to {checkpoint_file}"
        except Exception as e:
            return False, f"Failed to save checkpoint: {str(e)}"
    
    def load_checkpoint(self, sync_config: dict) -> tuple:
        """Load checkpoint data if it exists"""
        try:
            checkpoint_file = self.get_checkpoint_file(sync_config)
            if not os.path.exists(checkpoint_file):
                return None, "No checkpoint found"
            
            with open(checkpoint_file, 'r', encoding='utf-8') as f:
                checkpoint_data = json.load(f)
            
            # Check if checkpoint is recent (less than 24 hours old)
            last_updated = datetime.fromisoformat(checkpoint_data.get('last_updated', ''))
            hours_ago = (datetime.now() - last_updated).total_seconds() / 3600
            
            return checkpoint_data, f"Found checkpoint from {hours_ago:.1f} hours ago"
        except Exception as e:
            return None, f"Failed to load checkpoint: {str(e)}"
    
    def delete_checkpoint(self, sync_config: dict) -> tuple:
        """Delete checkpoint file when sync completes successfully"""
        try:
            checkpoint_file = self.get_checkpoint_file(sync_config)
            if os.path.exists(checkpoint_file):
                os.remove(checkpoint_file)
                return True, "Checkpoint cleaned up"
            return True, "No checkpoint to clean"
        except Exception as e:
            return False, f"Failed to delete checkpoint: {str(e)}"
    
    def list_active_checkpoints(self) -> list:
        """List all active checkpoint files"""
        checkpoints = []
        try:
            for filename in os.listdir(self.checkpoint_dir):
                if filename.startswith("sync_checkpoint_") and filename.endswith(".json"):
                    filepath = os.path.join(self.checkpoint_dir, filename)
                    try:
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                        checkpoints.append({
                            'file': filename,
                            'last_updated': data.get('last_updated'),
                            'processed_count': len(data.get('processed_items', [])),
                            'total_items': data.get('total_items', 0)
                        })
                    except Exception:
                        continue
        except Exception:
            pass
        return checkpoints

class RallyJiraReverseSync:
    """Rally to Jira reverse synchronization class"""
    
    def __init__(self, jira_url: str, jira_user: str, jira_token: str, jira_project: str,
                 rally_url: str, rally_api_key: str, rally_workspace: str,
                 rally_project: str, status_mappings: Dict[str, str]):
        self.jira_url = jira_url
        self.jira_user = jira_user
        self.jira_token = jira_token
        self.jira_project = jira_project
        self.rally_url = rally_url
        self.rally_api_key = rally_api_key
        self.rally_workspace = rally_workspace
        self.rally_project = rally_project
        self.status_mappings = status_mappings
        
        self.jira_client = None
        self.rally_client = None
        self.rally_auth_headers = None
        self.rally_base_url = None
        self.logger = logging.getLogger(__name__)
        
        # Initialize checkpoint manager
        self.checkpoint_manager = SyncCheckpointManager()
    
    def connect_to_jira(self):
        """Connect to Jira"""
        try:
            self.jira_client = JIRA(
                server=self.jira_url,
                basic_auth=(self.jira_user, self.jira_token)
            )
            # Test connection
            self.jira_client.current_user()
            return True, "Jira connection successful"
        except Exception as e:
            return False, f"Jira connection failed: {str(e)}"
    
    def connect_to_rally(self):
        """Connect to Rally using REST API with Basic Authentication"""
        try:
            import base64
            
            # Use the working authentication method discovered by diagnostic
            auth_header = base64.b64encode(f"{self.rally_api_key}:".encode()).decode()
            
            headers = {
                'Authorization': f'Basic {auth_header}',
                'Content-Type': 'application/json',
                'Accept': 'application/json',
                'X-RallyIntegrationName': 'JiraRallySync',
                'X-RallyIntegrationVendor': 'Custom',
                'X-RallyIntegrationVersion': '1.0'
            }
            
            # Test authentication
            auth_url = f"{self.rally_url}/slm/webservice/v2.0/security/authorize"
            
            self.logger.info(f"Testing Rally connection to: {self.rally_url}")
            response = requests.get(auth_url, headers=headers, timeout=20)
            
            if response.status_code == 200:
                try:
                    data = response.json()
                    if 'OperationResult' in data:
                        errors = data.get('OperationResult', {}).get('Errors', [])
                        if not errors:
                            user_name = data.get('User', {}).get('_refObjectName', 'Unknown User')
                            self.logger.info(f"Rally authentication successful as: {user_name}")
                            
                            # Store authentication headers for future requests
                            self.rally_auth_headers = headers
                            self.rally_base_url = f"{self.rally_url}/slm/webservice/v2.0"
                            
                            # Also fetch available projects to help with troubleshooting
                            try:
                                projects_url = f"{self.rally_base_url}/project"
                                projects_params = {'pagesize': 20, 'fetch': 'Name,ObjectID,Workspace'}
                                projects_response = requests.get(projects_url, headers=headers, timeout=20, params=projects_params)
                                if projects_response.status_code == 200:
                                    projects_data = projects_response.json()
                                    projects = projects_data.get('QueryResult', {}).get('Results', [])
                                    project_names = []
                                    for p in projects:
                                        name = p.get('Name', 'Unknown')
                                        obj_id = p.get('ObjectID', '')
                                        workspace_name = p.get('Workspace', {}).get('_refObjectName', 'Unknown')
                                        project_names.append(f"{name} (ID:{obj_id}, WS:{workspace_name})")
                                    
                                    if project_names:
                                        self.logger.info(f"Available Rally projects sample: {', '.join(project_names[:3])}{'...' if len(project_names) > 3 else ''}")
                                        self.logger.info(f"Total {len(project_names)} projects accessible")
                                    else:
                                        self.logger.warning("No Rally projects found - check workspace access")
                            except Exception as e:
                                self.logger.warning(f"Could not list Rally projects: {e}")
                            
                            return True, f"Rally connection successful as {user_name}"
                        else:
                            return False, f"Rally authentication errors: {errors}"
                    else:
                        return False, "Unexpected Rally response format"
                except json.JSONDecodeError:
                    return False, "Rally returned non-JSON response"
            else:
                return False, f"Rally authentication failed with status {response.status_code}: {response.text[:200]}"
                
        except Exception as e:
            return False, f"Rally connection failed: {str(e)}"
    
    def get_rally_items(self, item_types: List[str], rally_filter: str = None) -> List[Dict]:
        """Fetch Rally items using REST API with improved query logic"""
        rally_items = []
        
        if not hasattr(self, 'rally_auth_headers'):
            self.logger.error("Rally not connected. Call connect_to_rally() first.")
            return []
        
        # Determine if rally_project is ObjectID or Name
        project_is_objectid = self.rally_project.isdigit()
        
        for item_type in item_types:
            try:
                self.logger.info(f"Fetching Rally {item_type}s...")
                
                # Build query with workspace and project context
                if project_is_objectid:
                    # Use ObjectID reference
                    project_criteria = f'(Project.ObjectID = {self.rally_project})'
                else:
                    # Escape project name for Rally query - handle special characters
                    escaped_project = self.rally_project.replace('|', '\\\\|')
                    project_criteria = f'(Project.Name = "{escaped_project}")'
                
                # Use project criteria only - workspace is handled via API parameter
                query_criteria = project_criteria
                
                # Add additional filter if provided
                if rally_filter:
                    query_criteria += f" AND ({rally_filter})"
                
                self.logger.debug(f"Rally query for {item_type}: {query_criteria}")
                
                # Construct REST API URL with pagination support
                url = f"{self.rally_base_url}/{item_type.lower()}"
                base_params = {
                    'query': query_criteria,
                    'fetch': 'FormattedID,Name,Description,State,ScheduleState,ObjectID,Project,Workspace',
                    'order': 'FormattedID',
                    'pagesize': 200  # Fetch in batches of 200
                }
                
                # Add workspace parameter for API call if available
                if hasattr(self, 'rally_workspace') and self.rally_workspace:
                    if self.rally_workspace.isdigit():
                        base_params['workspace'] = f'/workspace/{self.rally_workspace}'
                
                # DEBUG: Log exact URL and parameters
                self.logger.info(f"Rally API URL: {url}")
                self.logger.info(f"Rally API params: {base_params}")
                self.logger.info(f"Rally workspace: {getattr(self, 'rally_workspace', 'NOT SET')}")
                
                # Implement pagination to fetch ALL items
                all_results = []
                start_index = 1
                total_fetched = 0
                
                while True:
                    # Add pagination parameters
                    params = base_params.copy()
                    params['start'] = start_index
                    
                    self.logger.debug(f"Fetching {item_type} batch starting at {start_index}")
                    
                    response = requests.get(url, headers=self.rally_auth_headers, params=params, timeout=30)
                    
                    if response.status_code != 200:
                        error_details = f"Status: {response.status_code}, Response: {response.text[:500]}"
                        self.logger.error(f"Failed to fetch {item_type}s: {error_details}")
                        break
                    
                    data = response.json()
                    query_result = data.get('QueryResult', {})
                    results = query_result.get('Results', [])
                    total_count = query_result.get('TotalResultCount', 0)
                    
                    self.logger.info(f"Rally API batch returned {len(results)} of {total_count} total {item_type}s (fetched {total_fetched + len(results)} so far)")
                    
                    # Add results to our collection
                    all_results.extend(results)
                    total_fetched += len(results)
                    
                    # Check if we have all items
                    if len(results) < base_params['pagesize'] or total_fetched >= total_count:
                        self.logger.info(f"Completed fetching all {total_fetched} {item_type}s")
                        break
                    
                    # Move to next batch
                    start_index += len(results)

                # Process all fetched results
                    
                # Process all fetched results
                for item in all_results:
                    # Handle different item types and their state fields
                    state_value = item.get('State') or item.get('ScheduleState')
                    
                    rally_items.append({
                        'FormattedID': item.get('FormattedID'),
                        'Name': item.get('Name'),
                        'Description': item.get('Description'),
                        'Type': item_type,
                        'State': state_value,
                        'ObjectID': item.get('ObjectID'),
                        'ref': item.get('_ref'),
                        'Project': item.get('Project', {}),
                        'Workspace': item.get('Workspace', {})
                    })
                
                self.logger.info(f"Total {item_type}s collected: {len(all_results)}")
                    
            except Exception as e:
                self.logger.error(f"Error fetching Rally {item_type}s: {e}")
        
        self.logger.info(f"Total Rally items found: {len(rally_items)}")
        return rally_items
    
    def get_single_rally_item(self, formatted_id: str) -> Optional[Dict]:
        """Fetch a single Rally item by FormattedID using the same logic as bulk fetch"""
        if not hasattr(self, 'rally_auth_headers'):
            self.logger.error("Rally not connected. Call connect_to_rally() first.")
            return None
        
        # Determine item type from FormattedID prefix
        item_type_map = {
            'US': 'hierarchicalrequirement',
            'DE': 'defect', 
            'TA': 'task',
            'TC': 'testcase'
        }
        
        prefix = formatted_id[:2].upper() if len(formatted_id) >= 2 else formatted_id[:1].upper()
        item_type = item_type_map.get(prefix, 'hierarchicalrequirement')
        
        try:
            self.logger.info(f"Fetching Rally item {formatted_id} (type: {item_type})")
            
            # Use the same query logic as the working bulk fetch
            project_is_objectid = self.rally_project.isdigit()
            
            if project_is_objectid:
                # Use ObjectID reference (same as bulk fetch)
                project_criteria = f'(Project.ObjectID = {self.rally_project})'
            else:
                # Escape project name for Rally query - handle special characters
                escaped_project = self.rally_project.replace('|', '\\\\|')
                project_criteria = f'(Project.Name = "{escaped_project}")'
            
            # Use FormattedID-only query - workspace parameter constrains to correct project
            # This avoids Rally's AND syntax parsing issues  
            query_criteria = f'(FormattedID = "{formatted_id}")'
            
            self.logger.debug(f"Rally single item query: {query_criteria}")
            
            # Use the same URL structure as bulk fetch
            url = f"{self.rally_base_url}/{item_type.lower()}"
            params = {
                'query': query_criteria,
                'fetch': 'FormattedID,Name,Description,State,ScheduleState,ObjectID,Project,Workspace',
                'pagesize': 1  # Only need 1 item
            }
            
            # Add workspace parameter if available (same as bulk fetch)
            if hasattr(self, 'rally_workspace') and self.rally_workspace:
                if self.rally_workspace.isdigit():
                    params['workspace'] = f'/workspace/{self.rally_workspace}'
            
            self.logger.debug(f"Rally single item URL: {url}")
            self.logger.debug(f"Rally single item params: {params}")
            
            # Make the request using same headers as bulk fetch
            response = requests.get(url, headers=self.rally_auth_headers, params=params, timeout=30)
            
            if response.status_code != 200:
                error_details = f"Status: {response.status_code}, Response: {response.text[:300]}"
                self.logger.error(f"Failed to fetch Rally item {formatted_id}: {error_details}")
                return None
            
            data = response.json()
            query_result = data.get('QueryResult', {})
            results = query_result.get('Results', [])
            total_count = query_result.get('TotalResultCount', 0)
            
            self.logger.info(f"Rally single item API returned {len(results)} of {total_count} results for {formatted_id}")
            
            if not results:
                self.logger.warning(f"Rally item {formatted_id} not found in project {self.rally_project}")
                return None
            
            # Process the found item (same as bulk fetch)
            item = results[0]
            state_value = item.get('State') or item.get('ScheduleState')
            
            rally_item = {
                'FormattedID': item.get('FormattedID'),
                'Name': item.get('Name'),
                'Description': item.get('Description'),
                'Type': item_type,
                'State': state_value,
                'ObjectID': item.get('ObjectID'),
                'ref': item.get('_ref'),
                'Project': item.get('Project', {}),
                'Workspace': item.get('Workspace', {})
            }
            
            self.logger.info(f"Successfully fetched Rally item: {formatted_id} - {item.get('Name', 'N/A')[:60]}")
            return rally_item
            
        except Exception as e:
            self.logger.error(f"Error fetching Rally item {formatted_id}: {e}")
            return None
    
    def search_jira_for_rally_item(self, rally_formatted_id: str) -> Optional[Dict]:
        """Search Jira for a Rally item by FormattedID"""
        try:
            # Search in multiple fields
            jql_queries = [
                f'summary ~ "{rally_formatted_id}"',
                f'description ~ "{rally_formatted_id}"',
                f'comment ~ "{rally_formatted_id}"'
            ]
            
            for jql in jql_queries:
                try:
                    issues = self.jira_client.search_issues(jql, maxResults=5)
                    if issues:
                        issue = issues[0]  # Take first match
                        return {
                            'key': issue.key,
                            'summary': issue.fields.summary,
                            'status': issue.fields.status.name,
                            'issue_type': issue.fields.issuetype.name
                        }
                except:
                    continue
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error searching Jira for {rally_formatted_id}: {e}")
            return None
    
    def get_rally_status_for_jira_status(self, jira_status: str, rally_item_type: str = None) -> str:
        """Map Jira status to Rally status based on artifact type"""
        # Handle both old (simple dict) and new (artifact-type-specific) mapping formats
        if isinstance(self.status_mappings, dict):
            # Check if it's the new format with artifact types
            if rally_item_type and rally_item_type.lower() in self.status_mappings:
                artifact_mappings = self.status_mappings[rally_item_type.lower()]
                return artifact_mappings.get(jira_status, jira_status)
            # Handle old format or fallback
            elif any(isinstance(v, dict) for v in self.status_mappings.values()):
                # New format but no matching type, use defect as default
                default_type = 'defect'
                if default_type in self.status_mappings:
                    return self.status_mappings[default_type].get(jira_status, jira_status)
            else:
                # Old simple format
                return self.status_mappings.get(jira_status, jira_status)
        
        return jira_status
    
    def update_rally_item_status(self, rally_item: Dict, new_status: str, dry_run: bool = False) -> Tuple[bool, str]:
        """Update Rally item status using REST API"""
        try:
            if dry_run:
                return True, f"DRY RUN: Would update {rally_item['FormattedID']} to {new_status}"
            
            if not hasattr(self, 'rally_auth_headers'):
                return False, "Rally not connected. Call connect_to_rally() first."
            
            # Determine status field based on item type
            status_field = 'ScheduleState' if rally_item['Type'] == 'HierarchicalRequirement' else 'State'
            
            # Construct update URL
            object_id = rally_item['ObjectID']
            item_type = rally_item['Type'].lower()
            url = f"{self.rally_base_url}/{item_type}/{object_id}"
            
            # Prepare update data
            update_data = {
                item_type.capitalize(): {
                    status_field: new_status
                }
            }
            
            response = requests.post(
                url, 
                headers=self.rally_auth_headers, 
                json=update_data, 
                timeout=30
            )
            
            if response.status_code == 200:
                data = response.json()
                operation_result = data.get('OperationResult', {})
                
                if operation_result.get('Errors', []):
                    errors = operation_result['Errors']
                    return False, f"Rally update errors: {errors}"
                else:
                    return True, f"Updated {rally_item['FormattedID']} status to {new_status}"
            else:
                return False, f"Rally update failed: {response.status_code} - {response.text[:200]}"
            
        except Exception as e:
            return False, f"Error updating {rally_item['FormattedID']}: {str(e)}"
    
    def extract_jira_keys_from_rally_item(self, rally_item: Dict) -> List[str]:
        """Extract JIRA keys (like CAM-xxx) from Rally item name and description"""
        jira_keys = []
        
        # Pattern 1: JIRA|Type|KEY|Description format
        pattern1 = r'JIRA\|[^|]*\|([A-Z]+-\d+)\|'
        
        # Pattern 2: Direct JIRA key mentions like CAM-2268, PROJ-123
        pattern2 = r'\b([A-Z]{2,10}-\d+)\b'
        
        # Search in Rally item name
        if rally_item.get('Name'):
            matches1 = re.findall(pattern1, rally_item['Name'], re.IGNORECASE)
            jira_keys.extend([m.upper() for m in matches1])
            
            matches2 = re.findall(pattern2, rally_item['Name'], re.IGNORECASE)
            jira_keys.extend([m.upper() for m in matches2])
        
        # Search in description if available
        if rally_item.get('Description'):
            desc_matches1 = re.findall(pattern1, rally_item['Description'], re.IGNORECASE)
            jira_keys.extend([m.upper() for m in desc_matches1])
            
            desc_matches2 = re.findall(pattern2, rally_item['Description'], re.IGNORECASE)
            jira_keys.extend([m.upper() for m in desc_matches2])
        
        # Remove duplicates while preserving order
        unique_jira_keys = list(dict.fromkeys(jira_keys))
        return unique_jira_keys

    def sync_rally_with_jira_cam_references(self, item_types: List[str], rally_filter: str = None, 
                                          dry_run: bool = False, progress_callback=None) -> Dict:
        """
        New sync function that extracts CAM-xxx (and other) JIRA references from Rally work item names
        and updates Rally status to match the referenced JIRA ticket status
        """
        results = {
            'total_rally_items': 0,
            'rally_items_with_jira_refs': 0,
            'jira_tickets_found': 0,
            'successful_updates': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            # Connect to services
            jira_success, jira_msg = self.connect_to_jira()
            rally_success, rally_msg = self.connect_to_rally()
            
            if not jira_success:
                results['details'].append(f"ERROR: {jira_msg}")
                return results
            
            if not rally_success:
                results['details'].append(f"ERROR: {rally_msg}")
                return results
            
            # Get Rally items
            if progress_callback:
                progress_callback(10, f"Fetching Rally items: {', '.join(item_types)} from project '{self.rally_project}'")
            
            self.logger.info(f"Fetching Rally items: {', '.join(item_types)} from project '{self.rally_project}'")
            rally_items = self.get_rally_items(item_types, rally_filter)
            results['total_rally_items'] = len(rally_items)
            
            if progress_callback:
                progress_callback(20, f"Found {len(rally_items)} Rally items")
            
            self.logger.info(f"Found {len(rally_items)} Rally items")
            
            if not rally_items:
                error_msg = f"No Rally items found with the specified criteria in project '{self.rally_project}'"
                if rally_filter:
                    error_msg += f" with filter: {rally_filter}"
                results['details'].append(error_msg) 
                self.logger.warning(error_msg)
                if progress_callback:
                    progress_callback(100, error_msg)
                return results
            
            self.logger.info(f"Processing {len(rally_items)} Rally items for JIRA key extraction...")
            
            # Process each Rally item
            items_processed = 0
            for i, rally_item in enumerate(rally_items):
                if progress_callback:
                    progress = 20 + (i + 1) / len(rally_items) * 70  # Progress from 20% to 90%
                    progress_callback(progress, f"Processing {rally_item['FormattedID']} - extracting JIRA keys...")
                
                self.logger.debug(f"Processing Rally item {rally_item['FormattedID']}: {rally_item.get('Name', 'N/A')[:80]}...")
                
                # Extract JIRA keys from Rally item name/description
                jira_keys = self.extract_jira_keys_from_rally_item(rally_item)
                
                if not jira_keys:
                    self.logger.debug(f"No JIRA keys found in {rally_item['FormattedID']}")
                    results['details'].append({
                        'rally_id': rally_item['FormattedID'],
                        'rally_name': rally_item.get('Name', 'N/A'),
                        'action': 'no_jira_references',
                        'message': f"No JIRA key patterns (CAM-xxx, etc.) found in Rally item name or description"
                    })
                    continue
                
                results['rally_items_with_jira_refs'] += 1
                self.logger.info(f"Found JIRA keys in {rally_item['FormattedID']}: {', '.join(jira_keys)}")
                
                if progress_callback:
                    progress_callback(progress, f"Found JIRA keys in {rally_item['FormattedID']}: {', '.join(jira_keys)}")
                
                # Process each extracted JIRA key
                for jira_key in jira_keys:
                    try:
                        self.logger.debug(f"Looking up JIRA issue: {jira_key}")
                        # Get JIRA issue directly by key
                        jira_issue = self.jira_client.issue(jira_key)
                        results['jira_tickets_found'] += 1
                        
                        # Get current Rally status
                        current_rally_status = rally_item.get('State') or rally_item.get('ScheduleState') or 'Unknown'
                        
                        # Get target Rally status based on JIRA status
                        jira_status = jira_issue.fields.status.name
                        rally_type = rally_item.get('_type', '').lower() or rally_item.get('Type', '').lower()
                        target_rally_status = self.get_rally_status_for_jira_status(jira_status, rally_type)
                        
                        status_comparison = f"{rally_item['FormattedID']} -> {jira_key}: Rally '{current_rally_status}' vs JIRA '{jira_status}' -> Target '{target_rally_status}'"
                        self.logger.info(status_comparison)
                        
                        if progress_callback:
                            progress_callback(progress, status_comparison)
                        
                        if current_rally_status != target_rally_status:
                            # Update Rally item status
                            if not dry_run:
                                success, message = self.update_rally_item_status(
                                    rally_item, target_rally_status, dry_run
                                )
                            else:
                                success = True
                                message = f"DRY RUN: Would update {rally_item['FormattedID']} status to {target_rally_status}"
                            
                            if success:
                                results['successful_updates'] += 1
                                self.logger.info(f"{'DRY RUN: Would update' if dry_run else 'Updated'} {rally_item['FormattedID']}: {current_rally_status} -> {target_rally_status}")
                                results['details'].append({
                                    'rally_id': rally_item['FormattedID'],
                                    'rally_name': rally_item.get('Name', 'N/A')[:50] + '...' if len(rally_item.get('Name', '')) > 50 else rally_item.get('Name', 'N/A'),
                                    'extracted_jira_key': jira_key,
                                    'jira_summary': jira_issue.fields.summary[:60] + '...' if len(jira_issue.fields.summary) > 60 else jira_issue.fields.summary,
                                    'action': 'status_updated' if not dry_run else 'dry_run_update',
                                    'old_rally_status': current_rally_status,
                                    'new_rally_status': target_rally_status,
                                    'jira_status': jira_status,
                                    'message': message
                                })
                            else:
                                results['errors'] += 1
                                self.logger.error(f"Failed to update {rally_item['FormattedID']}: {message}")
                                results['details'].append({
                                    'rally_id': rally_item['FormattedID'],
                                    'extracted_jira_key': jira_key,
                                    'action': 'error',
                                    'message': message
                                })
                        else:
                            self.logger.debug(f"No update needed for {rally_item['FormattedID']}: status already matches ({current_rally_status})")
                            results['details'].append({
                                'rally_id': rally_item['FormattedID'],
                                'rally_name': rally_item.get('Name', 'N/A')[:50] + '...' if len(rally_item.get('Name', '')) > 50 else rally_item.get('Name', 'N/A'),
                                'extracted_jira_key': jira_key,
                                'jira_summary': jira_issue.fields.summary[:60] + '...' if len(jira_issue.fields.summary) > 60 else jira_issue.fields.summary,
                                'action': 'no_update_needed',
                                'rally_status': current_rally_status,
                                'jira_status': jira_status,
                                'message': f"Rally status ({current_rally_status}) already matches target status for JIRA {jira_key}"
                            })
                        
                        # Only process the first JIRA key found for each Rally item to avoid conflicts
                        break
                        
                    except Exception as jira_error:
                        self.logger.warning(f"JIRA ticket {jira_key} not found or access denied: {jira_error}")
                        results['details'].append({
                            'rally_id': rally_item['FormattedID'],
                            'extracted_jira_key': jira_key,
                            'action': 'jira_ticket_not_found',
                            'message': f"Could not fetch JIRA ticket {jira_key}: {str(jira_error)}"
                        })
                        continue
                
                items_processed += 1
            
            if progress_callback:
                progress_callback(95, f"Completed processing {items_processed} Rally items")
            
            # Log final summary
            self.logger.info(f"CAM-xxx Sync Summary: {results['total_rally_items']} Rally items, {results['rally_items_with_jira_refs']} with JIRA refs, {results['jira_tickets_found']} JIRA tickets found, {results['successful_updates']} updates, {results['errors']} errors")
            return results
            
        except Exception as e:
            results['details'].append(f"SYNC ERROR: {str(e)}")
            results['errors'] += 1
            return results

    def sync_rally_with_jira_cam_references_resumable(self, item_types: List[str], rally_filter: str = None, 
                                                     dry_run: bool = False, progress_callback=None, 
                                                     enable_checkpoints: bool = True, resume_from_checkpoint: bool = False) -> Dict:
        """
        Enhanced sync function with checkpoint support for resuming interrupted syncs
        """
        results = {
            'total_rally_items': 0,
            'rally_items_with_jira_refs': 0,
            'jira_tickets_found': 0,
            'successful_updates': 0,
            'errors': 0,
            'details': [],
            'resumed_from_checkpoint': False,
            'checkpoint_info': None
        }
        
        # Generate sync configuration for checkpoint management
        sync_config = {
            'item_types': sorted(item_types),
            'rally_filter': rally_filter or "",
            'rally_project': self.rally_project,
            'rally_workspace': self.rally_workspace,
            'jira_project': self.jira_project,
            'sync_mode': 'cam_references'
        }
        
        processed_items = set()
        checkpoint_data = None
        
        try:
            # Check for existing checkpoint if enabled
            if enable_checkpoints and resume_from_checkpoint:
                checkpoint_data, checkpoint_msg = self.checkpoint_manager.load_checkpoint(sync_config)
                if checkpoint_data:
                    processed_items = set(checkpoint_data.get('processed_items', []))
                    results['resumed_from_checkpoint'] = True
                    results['checkpoint_info'] = checkpoint_msg
                    self.logger.info(f"Resuming from checkpoint: {checkpoint_msg}")
                    self.logger.info(f"Already processed {len(processed_items)} items, will skip those")
                    if progress_callback:
                        progress_callback(5, f"Resuming sync - {len(processed_items)} items already processed")
                else:
                    self.logger.info(f"No checkpoint found or could not load: {checkpoint_msg}")
            
            # Connect to services
            jira_success, jira_msg = self.connect_to_jira()
            rally_success, rally_msg = self.connect_to_rally()
            
            if not jira_success:
                results['details'].append(f"ERROR: {jira_msg}")
                return results
            
            if not rally_success:
                results['details'].append(f"ERROR: {rally_msg}")
                return results
            
            # Get Rally items
            if progress_callback:
                progress_callback(10, f"Fetching Rally items: {', '.join(item_types)} from project '{self.rally_project}'")
            
            self.logger.info(f"Fetching Rally items: {', '.join(item_types)} from project '{self.rally_project}'")
            rally_items = self.get_rally_items(item_types, rally_filter)
            results['total_rally_items'] = len(rally_items)
            
            if not rally_items:
                error_msg = f"No Rally items found with the specified criteria in project '{self.rally_project}'"
                if rally_filter:
                    error_msg += f" with filter: {rally_filter}"
                results['details'].append(error_msg) 
                self.logger.warning(error_msg)
                if progress_callback:
                    progress_callback(100, error_msg)
                return results
            
            # Filter out already processed items if resuming
            if processed_items:
                original_count = len(rally_items)
                rally_items = [item for item in rally_items if item['FormattedID'] not in processed_items]
                skipped_count = original_count - len(rally_items)
                self.logger.info(f"Skipping {skipped_count} already processed items, {len(rally_items)} remaining")
                if progress_callback:
                    progress_callback(15, f"Skipped {skipped_count} already processed items, processing {len(rally_items)} remaining")
            
            if progress_callback:
                progress_callback(20, f"Processing {len(rally_items)} Rally items")
            
            self.logger.info(f"Processing {len(rally_items)} Rally items for JIRA key extraction...")
            
            # Initialize checkpoint data if enabled
            if enable_checkpoints:
                checkpoint_save_interval = max(1, len(rally_items) // 20)  # Save every 5% of items
                if not checkpoint_data:
                    checkpoint_data = {
                        'processed_items': list(processed_items),
                        'total_items': results['total_rally_items'],
                        'start_time': datetime.now().isoformat()
                    }
            
            # Process each Rally item
            items_processed = 0
            for i, rally_item in enumerate(rally_items):
                rally_id = rally_item['FormattedID']
                
                # Skip if already processed (safety check)
                if rally_id in processed_items:
                    continue
                
                if progress_callback:
                    # Calculate progress considering already processed items
                    total_progress = ((len(processed_items) + i + 1) / results['total_rally_items']) * 70 + 20
                    progress_callback(total_progress, f"Processing {rally_id} - extracting JIRA keys...")
                
                self.logger.debug(f"Processing Rally item {rally_id}: {rally_item.get('Name', 'N/A')[:80]}...")
                
                try:
                    # Extract JIRA keys from Rally item name/description
                    jira_keys = self.extract_jira_keys_from_rally_item(rally_item)
                    
                    if not jira_keys:
                        self.logger.debug(f"No JIRA keys found in {rally_id}")
                        results['details'].append({
                            'rally_id': rally_id,
                            'rally_name': rally_item.get('Name', 'N/A'),
                            'action': 'no_jira_references',
                            'message': f"No JIRA key patterns (CAM-xxx, etc.) found in Rally item name or description"
                        })
                        # Mark as processed even if no JIRA keys found
                        processed_items.add(rally_id)
                        continue
                    
                    results['rally_items_with_jira_refs'] += 1
                    self.logger.info(f"Found JIRA keys in {rally_id}: {', '.join(jira_keys)}")
                    
                    # Process JIRA keys for this Rally item
                    for jira_key in jira_keys:
                        try:
                            self.logger.debug(f"Looking up JIRA issue: {jira_key}")
                            jira_issue = self.jira_client.issue(jira_key)
                            results['jira_tickets_found'] += 1
                            
                            # Get current Rally status
                            current_rally_status = rally_item.get('State') or rally_item.get('ScheduleState') or 'Unknown'
                            jira_status = jira_issue.fields.status.name
                            rally_type = rally_item.get('_type', '').lower() or rally_item.get('Type', '').lower()
                            target_rally_status = self.get_rally_status_for_jira_status(jira_status, rally_type)
                            
                            status_comparison = f"{rally_id} -> {jira_key}: Rally '{current_rally_status}' vs JIRA '{jira_status}' -> Target '{target_rally_status}'"
                            self.logger.info(status_comparison)
                            
                            if current_rally_status != target_rally_status:
                                # Update Rally item status
                                if not dry_run:
                                    success, message = self.update_rally_item_status(rally_item, target_rally_status, dry_run)
                                else:
                                    success = True
                                    message = f"DRY RUN: Would update {rally_id} status to {target_rally_status}"
                                
                                if success:
                                    results['successful_updates'] += 1
                                    self.logger.info(f"{'DRY RUN: Would update' if dry_run else 'Updated'} {rally_id}: {current_rally_status} -> {target_rally_status}")
                                    results['details'].append({
                                        'rally_id': rally_id,
                                        'rally_name': rally_item.get('Name', 'N/A')[:50] + '...' if len(rally_item.get('Name', '')) > 50 else rally_item.get('Name', 'N/A'),
                                        'extracted_jira_key': jira_key,
                                        'jira_summary': jira_issue.fields.summary[:60] + '...' if len(jira_issue.fields.summary) > 60 else jira_issue.fields.summary,
                                        'action': 'updated',
                                        'rally_status': current_rally_status,
                                        'jira_status': jira_status,
                                        'new_status': target_rally_status,
                                        'message': message
                                    })
                                else:
                                    results['errors'] += 1
                                    self.logger.error(f"Failed to update {rally_id}: {message}")
                                    results['details'].append({
                                        'rally_id': rally_id,
                                        'extracted_jira_key': jira_key,
                                        'action': 'update_failed',
                                        'message': message
                                    })
                            else:
                                self.logger.debug(f"No update needed for {rally_id}: status already matches ({current_rally_status})")
                                results['details'].append({
                                    'rally_id': rally_id,
                                    'rally_name': rally_item.get('Name', 'N/A')[:50] + '...' if len(rally_item.get('Name', '')) > 50 else rally_item.get('Name', 'N/A'),
                                    'extracted_jira_key': jira_key,
                                    'jira_summary': jira_issue.fields.summary[:60] + '...' if len(jira_issue.fields.summary) > 60 else jira_issue.fields.summary,
                                    'action': 'no_update_needed',
                                    'rally_status': current_rally_status,
                                    'jira_status': jira_status,
                                    'message': f"Rally status ({current_rally_status}) already matches target status for JIRA {jira_key}"
                                })
                            
                            # Only process the first JIRA key found for each Rally item to avoid conflicts
                            break
                            
                        except Exception as jira_error:
                            self.logger.warning(f"JIRA ticket {jira_key} not found or access denied: {jira_error}")
                            results['details'].append({
                                'rally_id': rally_id,
                                'extracted_jira_key': jira_key,
                                'action': 'jira_ticket_not_found',
                                'message': f"Could not fetch JIRA ticket {jira_key}: {str(jira_error)}"
                            })
                            continue
                
                except Exception as item_error:
                    self.logger.error(f"Error processing Rally item {rally_id}: {item_error}")
                    results['errors'] += 1
                    results['details'].append({
                        'rally_id': rally_id,
                        'action': 'processing_error',
                        'message': f"Error processing item: {str(item_error)}"
                    })
                
                finally:
                    # Mark item as processed
                    processed_items.add(rally_id)
                    items_processed += 1
                    
                    # Save checkpoint periodically if enabled
                    if enable_checkpoints and items_processed % checkpoint_save_interval == 0:
                        checkpoint_data['processed_items'] = list(processed_items)
                        checkpoint_data['current_progress'] = {
                            'items_processed': len(processed_items),
                            'results_summary': {
                                'jira_tickets_found': results['jira_tickets_found'],
                                'successful_updates': results['successful_updates'],
                                'errors': results['errors']
                            }
                        }
                        success, msg = self.checkpoint_manager.save_checkpoint(sync_config, checkpoint_data)
                        if success:
                            self.logger.debug(f"Checkpoint saved: {items_processed}/{len(rally_items)} items processed")
                        else:
                            self.logger.warning(f"Failed to save checkpoint: {msg}")
            
            if progress_callback:
                progress_callback(95, f"Completed processing {items_processed} Rally items")
            
            # Final checkpoint cleanup on successful completion
            if enable_checkpoints:
                success, msg = self.checkpoint_manager.delete_checkpoint(sync_config)
                self.logger.info(f"Sync completed successfully - {msg}")
            
            # Log final summary
            self.logger.info(f"CAM-xxx Sync Summary: {results['total_rally_items']} Rally items, {results['rally_items_with_jira_refs']} with JIRA refs, {results['jira_tickets_found']} JIRA tickets found, {results['successful_updates']} updates, {results['errors']} errors")
            return results
            
        except Exception as e:
            self.logger.error(f"Sync error: {str(e)}")
            # Save checkpoint on error if enabled
            if enable_checkpoints and checkpoint_data:
                checkpoint_data['processed_items'] = list(processed_items)
                checkpoint_data['error_info'] = {
                    'error_message': str(e),
                    'error_time': datetime.now().isoformat()
                }
                self.checkpoint_manager.save_checkpoint(sync_config, checkpoint_data)
            
            results['details'].append(f"SYNC ERROR: {str(e)}")
            results['errors'] += 1
            return results

    def sync_rally_to_jira(self, item_types: List[str], rally_filter: str = None, 
                          dry_run: bool = False, progress_callback=None) -> Dict:
        """Original sync function - searches for Rally IDs in JIRA"""
        results = {
            'total_rally_items': 0,
            'jira_matches_found': 0,
            'successful_updates': 0,
            'errors': 0,
            'details': []
        }
        
        try:
            # Connect to services
            jira_success, jira_msg = self.connect_to_jira()
            rally_success, rally_msg = self.connect_to_rally()
            
            if not jira_success:
                results['details'].append(f"ERROR: {jira_msg}")
                return results
            
            if not rally_success:
                results['details'].append(f"ERROR: {rally_msg}")
                return results
            
            # Get Rally items
            rally_items = self.get_rally_items(item_types, rally_filter)
            results['total_rally_items'] = len(rally_items)
            
            if not rally_items:
                results['details'].append("No Rally items found with the specified criteria")
                return results
            
            # Process each Rally item
            for i, rally_item in enumerate(rally_items):
                if progress_callback:
                    progress = (i + 1) / len(rally_items) * 100
                    progress_callback(progress, f"Processing {rally_item['FormattedID']}...")
                
                # Search for Rally item in Jira
                jira_match = self.search_jira_for_rally_item(rally_item['FormattedID'])
                
                if jira_match:
                    results['jira_matches_found'] += 1
                    
                    # Check if status update is needed
                    current_rally_status = rally_item['State'] or 'Unknown'
                    rally_type = rally_item.get('_type', '').lower() or rally_item.get('Type', '').lower()
                    target_rally_status = self.get_rally_status_for_jira_status(jira_match['status'], rally_type)
                    
                    if current_rally_status != target_rally_status:
                        # Update Rally item status
                        success, message = self.update_rally_item_status(
                            rally_item, target_rally_status, dry_run
                        )
                        
                        if success:
                            results['successful_updates'] += 1
                            results['details'].append({
                                'rally_id': rally_item['FormattedID'],
                                'jira_key': jira_match['key'], 
                                'action': 'status_updated',
                                'old_status': current_rally_status,
                                'new_status': target_rally_status,
                                'jira_status': jira_match['status'],
                                'message': message
                            })
                        else:
                            results['errors'] += 1
                            results['details'].append({
                                'rally_id': rally_item['FormattedID'],
                                'jira_key': jira_match['key'],
                                'action': 'error',
                                'message': message
                            })
                    else:
                        results['details'].append({
                            'rally_id': rally_item['FormattedID'],
                            'jira_key': jira_match['key'],
                            'action': 'no_update_needed',
                            'status': current_rally_status,
                            'message': f"Status already matches: {current_rally_status}"
                        })
                else:
                    results['details'].append({
                        'rally_id': rally_item['FormattedID'],
                        'action': 'no_jira_match',
                        'message': f"No matching Jira issue found for {rally_item['FormattedID']}"
                    })
            
            return results
            
        except Exception as e:
            results['details'].append(f"SYNC ERROR: {str(e)}")
            results['errors'] += 1
            return results

class RallyJiraReverseSyncGUI:
    """GUI for Rally to Jira reverse sync"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Rally to Jira Reverse Sync")
        self.root.geometry("1000x900")
        
        # Variables
        self.status_mappings = DEFAULT_STATUS_MAPPINGS.copy()
        self.sync_tool = None
        self.sync_thread = None
        self.stop_sync = False
        
        # Setup logging
        self.setup_logging()
        
        # Create GUI
        self.create_gui()
        
        # Load configuration if exists
        self.load_configuration()
    
    def setup_logging(self):
        """Setup logging"""
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)
    
    def create_gui(self):
        """Create main GUI"""
        # Create notebook for tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Create tabs
        self.create_config_tab()
        self.create_sync_tab()
        self.create_results_tab()
        self.create_logging_tab()
    
    def create_config_tab(self):
        """Create configuration tab"""
        config_frame = ttk.Frame(self.notebook)
        self.notebook.add(config_frame, text="Configuration")
        
        # Create canvas for scrolling
        canvas = tk.Canvas(config_frame)
        scrollbar = ttk.Scrollbar(config_frame, orient="vertical", command=canvas.yview)
        scrollable_frame = ttk.Frame(canvas)
        
        scrollable_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        
        # Title
        title_label = tk.Label(scrollable_frame, text="Rally to Jira Reverse Sync Configuration", 
                              font=("Arial", 14, "bold"), fg="#2E86C1")
        title_label.pack(pady=(10, 20))
        
        # Help text
        help_text = tk.Label(scrollable_frame, 
                            text="This tool fetches Rally items and updates their status based on matching Jira issues.\n"
                                 "No Rally Field ID needed - searches Jira for Rally FormattedIDs automatically!",
                            font=("Arial", 10), fg="gray", justify="center")
        help_text.pack(pady=(0, 20))
        
        # Jira Configuration
        jira_frame = ttk.LabelFrame(scrollable_frame, text="Jira Configuration", padding="15")
        jira_frame.pack(fill='x', padx=20, pady=10)
        
        tk.Label(jira_frame, text="Jira URL:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky='w', pady=5)
        self.jira_url_var = tk.StringVar()
        tk.Entry(jira_frame, textvariable=self.jira_url_var, width=50, font=("Arial", 10)).grid(row=0, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(jira_frame, text="User Email:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky='w', pady=5)
        self.jira_user_var = tk.StringVar()
        tk.Entry(jira_frame, textvariable=self.jira_user_var, width=50, font=("Arial", 10)).grid(row=1, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(jira_frame, text="API Token:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky='w', pady=5)
        self.jira_token_var = tk.StringVar()
        tk.Entry(jira_frame, textvariable=self.jira_token_var, width=50, show='*', font=("Arial", 10)).grid(row=2, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(jira_frame, text="Project Key:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky='w', pady=5)
        self.jira_project_var = tk.StringVar()
        tk.Entry(jira_frame, textvariable=self.jira_project_var, width=50, font=("Arial", 10)).grid(row=3, column=1, sticky='ew', padx=(10,0), pady=5)
        
        jira_frame.columnconfigure(1, weight=1)
        
        # Rally Configuration
        rally_frame = ttk.LabelFrame(scrollable_frame, text="Rally Configuration", padding="15")
        rally_frame.pack(fill='x', padx=20, pady=10)
        
        tk.Label(rally_frame, text="Rally URL:", font=("Arial", 10, "bold")).grid(row=0, column=0, sticky='w', pady=5)
        self.rally_url_var = tk.StringVar(value="https://rally1.rallydev.com")
        tk.Entry(rally_frame, textvariable=self.rally_url_var, width=50, font=("Arial", 10)).grid(row=0, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(rally_frame, text="API Key:", font=("Arial", 10, "bold")).grid(row=1, column=0, sticky='w', pady=5)
        self.rally_api_key_var = tk.StringVar()
        tk.Entry(rally_frame, textvariable=self.rally_api_key_var, width=50, show='*', font=("Arial", 10)).grid(row=1, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(rally_frame, text="Workspace:", font=("Arial", 10, "bold")).grid(row=2, column=0, sticky='w', pady=5)
        self.rally_workspace_var = tk.StringVar()
        tk.Entry(rally_frame, textvariable=self.rally_workspace_var, width=50, font=("Arial", 10)).grid(row=2, column=1, sticky='ew', padx=(10,0), pady=5)
        
        tk.Label(rally_frame, text="Project:", font=("Arial", 10, "bold")).grid(row=3, column=0, sticky='w', pady=5)
        self.rally_project_var = tk.StringVar()
        tk.Entry(rally_frame, textvariable=self.rally_project_var, width=50, font=("Arial", 10)).grid(row=3, column=1, sticky='ew', padx=(10,0), pady=5)
        
        rally_frame.columnconfigure(1, weight=1)
        
        # Status Mappings
        mapping_frame = ttk.LabelFrame(scrollable_frame, text="Status Mappings (Jira → Rally)", padding="15")
        mapping_frame.pack(fill='x', padx=20, pady=10)
        
        # Mapping controls
        mapping_controls = tk.Frame(mapping_frame)
        mapping_controls.pack(fill='x', pady=(0, 10))
        
        tk.Button(mapping_controls, text="Load Default", command=self.load_default_mappings,
                 bg="#3498DB", fg="white", font=("Arial", 9)).pack(side='left')
        tk.Button(mapping_controls, text="Load File", command=self.load_mappings_file,
                 bg="#27AE60", fg="white", font=("Arial", 9)).pack(side='left', padx=(10, 0))
        tk.Button(mapping_controls, text="Save File", command=self.save_mappings_file,
                 bg="#E67E22", fg="white", font=("Arial", 9)).pack(side='left', padx=(10, 0))
        
        # Mappings display
        columns = ('Artifact Type', 'Jira Status', 'Rally Status')
        self.mappings_tree = ttk.Treeview(mapping_frame, columns=columns, show='headings', height=4)
        
        for col in columns:
            self.mappings_tree.heading(col, text=col)
            self.mappings_tree.column(col, width=150)
        
        self.mappings_tree.pack(fill='both', expand=True)
        self.update_mappings_display()
        
        # Control buttons
        button_frame = tk.Frame(scrollable_frame)
        button_frame.pack(fill='x', padx=20, pady=20)
        
        tk.Button(button_frame, text="Test Connections", command=self.test_connections,
                 bg="#2ECC71", fg="white", font=("Arial", 12, "bold"), width=15).pack(side='left', padx=(0, 10))
        tk.Button(button_frame, text="Save Configuration", command=self.save_configuration,
                 bg="#3498DB", fg="white", font=("Arial", 12, "bold"), width=15).pack(side='left')
        
        # Pack canvas
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
    
    def create_sync_tab(self):
        """Create sync operations tab"""
        sync_frame = ttk.Frame(self.notebook)
        self.notebook.add(sync_frame, text="Sync Operations")
        
        # Title
        title_label = tk.Label(sync_frame, text="Rally to Jira Reverse Sync", 
                              font=("Arial", 16, "bold"), fg="#E74C3C")
        title_label.pack(pady=20)
        
        # Help section
        help_frame = ttk.LabelFrame(sync_frame, text="How It Works", padding="15")
        help_frame.pack(fill='x', padx=20, pady=10)
        
        help_text = """🔄 Sync Modes Available:

🎯 CAM-xxx Reference Mode (NEW):
• Extracts JIRA references (CAM-1234, PROJ-567, etc.) from Rally item names
• Gets status directly from the referenced JIRA ticket
• Updates Rally status to match that JIRA ticket
• Perfect for Rally items that contain JIRA ticket references

🔍 Rally ID Search Mode (Original):  
• Searches JIRA for issues containing Rally IDs (US123, DE456, etc.)
• Updates Rally status to match the corresponding JIRA issue status
• Uses your configured status mappings

✅ Benefits:
• No Rally Field ID configuration needed
• Safe dry-run mode to preview changes
• Detailed progress tracking and results"""
        
        tk.Label(help_frame, text=help_text, font=("Arial", 10), justify="left").pack(anchor='w')
        
        # Options
        options_frame = ttk.LabelFrame(sync_frame, text="Sync Options", padding="15")
        options_frame.pack(fill='x', padx=20, pady=10)
        
        # Sync mode selection
        tk.Label(options_frame, text="Sync Mode:", font=("Arial", 11, "bold")).pack(anchor='w')
        
        self.sync_mode_var = tk.StringVar(value="cam_references")
        
        sync_mode_frame = tk.Frame(options_frame)
        sync_mode_frame.pack(fill='x', pady=(5, 15))
        
        tk.Radiobutton(sync_mode_frame, text="🎯 CAM-xxx Reference Mode (Extract JIRA refs from Rally names)", 
                      variable=self.sync_mode_var, value="cam_references",
                      font=("Arial", 10), fg="#27AE60").pack(anchor='w')
        tk.Label(sync_mode_frame, text="   Best for Rally items containing JIRA ticket references like CAM-1234",
                font=("Arial", 9), fg="gray").pack(anchor='w', padx=(20, 0))
        
        tk.Radiobutton(sync_mode_frame, text="🔍 Rally ID Search Mode (Search JIRA for Rally IDs)", 
                      variable=self.sync_mode_var, value="rally_id_search",
                      font=("Arial", 10)).pack(anchor='w', pady=(5, 0))
        tk.Label(sync_mode_frame, text="   Best for JIRA issues that contain Rally IDs like US123, DE456",
                font=("Arial", 9), fg="gray").pack(anchor='w', padx=(20, 0))
        
        # Rally item types
        tk.Label(options_frame, text="Rally Item Types to Sync:", font=("Arial", 11, "bold")).pack(anchor='w', pady=(10, 0))
        
        item_types_frame = tk.Frame(options_frame)
        item_types_frame.pack(fill='x', pady=(5, 15))
        
        self.sync_user_stories = tk.BooleanVar(value=True)
        self.sync_defects = tk.BooleanVar(value=True) 
        self.sync_tasks = tk.BooleanVar(value=True)
        
        tk.Checkbutton(item_types_frame, text="User Stories", variable=self.sync_user_stories,
                      font=("Arial", 10)).pack(side='left', padx=(0, 20))
        tk.Checkbutton(item_types_frame, text="Defects", variable=self.sync_defects,
                      font=("Arial", 10)).pack(side='left', padx=(0, 20))
        tk.Checkbutton(item_types_frame, text="Tasks", variable=self.sync_tasks,
                      font=("Arial", 10)).pack(side='left')
        
        # Rally filter
        tk.Label(options_frame, text="Rally Query Filter (Optional):", font=("Arial", 11, "bold")).pack(anchor='w')
        self.rally_filter_var = tk.StringVar()
        tk.Entry(options_frame, textvariable=self.rally_filter_var, width=80, font=("Arial", 10)).pack(fill='x', pady=(5, 5))
        tk.Label(options_frame, text="Examples: (State = \"In-Progress\") OR (Iteration.Name = \"Sprint 1\")",
                font=("Arial", 9), fg="gray").pack(anchor='w')
        
        # Dry run option
        self.dry_run_var = tk.BooleanVar(value=True)
        tk.Checkbutton(options_frame, text="🛡️ Dry Run (Preview changes without updating Rally)",
                      variable=self.dry_run_var, font=("Arial", 11, "bold"), fg="#E74C3C").pack(anchor='w', pady=10)
        
        # Sync controls
        controls_frame = tk.Frame(sync_frame)
        controls_frame.pack(fill='x', padx=20, pady=20)
        
        self.sync_button = tk.Button(controls_frame, text="🚀 Start Sync", command=self.start_sync,
                                    bg="#27AE60", fg="white", font=("Arial", 14, "bold"), width=12)
        self.sync_button.pack(side='left', padx=(0, 15))
        
        self.stop_button = tk.Button(controls_frame, text="⛔ Stop", command=self.stop_sync_process,
                                    bg="#E74C3C", fg="white", font=("Arial", 14, "bold"), width=8, state='disabled')
        self.stop_button.pack(side='left')
        
        # Checkpoint management button
        self.checkpoint_button = tk.Button(controls_frame, text="🔄 Checkpoints", command=self.manage_checkpoints,
                                          bg="#9B59B6", fg="white", font=("Arial", 12, "bold"), width=12)
        self.checkpoint_button.pack(side='left', padx=(15, 0))
        
        # Single JIRA Issue Lookup Section
        lookup_frame = ttk.LabelFrame(sync_frame, text="🔍 Single JIRA Issue Lookup", padding="10")
        lookup_frame.pack(fill='x', padx=20, pady=(10, 5))
        
        tk.Label(lookup_frame, text="Enter JIRA Issue Key:", font=("Arial", 11, "bold")).pack(anchor='w')
        
        lookup_input_frame = tk.Frame(lookup_frame)
        lookup_input_frame.pack(fill='x', pady=(2, 5))
        
        self.jira_key_var = tk.StringVar()
        self.jira_key_entry = tk.Entry(lookup_input_frame, textvariable=self.jira_key_var, 
                                      font=("Arial", 11), width=20)
        self.jira_key_entry.pack(side='left', padx=(0, 10))
        
        self.lookup_button = tk.Button(lookup_input_frame, text="🔍 Lookup", command=self.lookup_jira_issue,
                                      bg="#3498DB", fg="white", font=("Arial", 11, "bold"))
        self.lookup_button.pack(side='left')
        
        tk.Label(lookup_frame, text="Example: PROJ-123, TICKET-456", 
                font=("Arial", 9), fg="gray").pack(anchor='w')
        
        # Rally ID to JIRA Issue Lookup Section
        rally_lookup_frame = ttk.LabelFrame(sync_frame, text="🎯 Rally ID to JIRA Issue Lookup", padding="10")
        rally_lookup_frame.pack(fill='x', padx=20, pady=(5, 5))
        
        tk.Label(rally_lookup_frame, text="Enter Rally ID (extracts JIRA key from Rally item name):", font=("Arial", 11, "bold")).pack(anchor='w')
        
        rally_lookup_input_frame = tk.Frame(rally_lookup_frame)
        rally_lookup_input_frame.pack(fill='x', pady=(2, 5))
        
        self.rally_id_var = tk.StringVar()
        self.rally_id_entry = tk.Entry(rally_lookup_input_frame, textvariable=self.rally_id_var, 
                                      font=("Arial", 11), width=20)
        self.rally_id_entry.pack(side='left', padx=(0, 10))
        
        self.rally_lookup_button = tk.Button(rally_lookup_input_frame, text="🔍 Find JIRA", command=self.lookup_rally_to_jira,
                                            bg="#E74C3C", fg="white", font=("Arial", 11, "bold"))
        self.rally_lookup_button.pack(side='left')
        
        tk.Label(rally_lookup_frame, text="Example: DE1125592 (finds CAM-2268 from name like 'JIRA|Bug|CAM-2268|Description')", 
                font=("Arial", 9), fg="gray").pack(anchor='w')
        
        # Rally lookup results display
        self.rally_lookup_results = scrolledtext.ScrolledText(rally_lookup_frame, height=3, width=80, 
                                                            font=("Arial", 9), bg="#F0F8FF")
        self.rally_lookup_results.pack(fill='x', pady=(5, 0))
        self.rally_lookup_results.insert('1.0', "Enter a Rally ID to extract JIRA key from Rally item name and find corresponding JIRA status.")
        self.rally_lookup_results.config(state='disabled')
        
        # Original JIRA lookup results display
        self.lookup_results = scrolledtext.ScrolledText(lookup_frame, height=3, width=80, 
                                                       font=("Arial", 9), bg="#F8F9FA")
        self.lookup_results.pack(fill='x', pady=(5, 0))
        self.lookup_results.insert('1.0', "Enter a JIRA issue key above and click 'Lookup' to find the corresponding Rally item status.")
        self.lookup_results.config(state='disabled')

        # Progress
        progress_frame = tk.Frame(sync_frame)
        progress_frame.pack(fill='x', padx=20, pady=10)
        
        self.progress_var = tk.StringVar(value="Ready to sync")
        tk.Label(progress_frame, textvariable=self.progress_var, font=("Arial", 10)).pack(anchor='w')
        
        self.progress_bar = ttk.Progressbar(progress_frame, length=400, mode='determinate')
        self.progress_bar.pack(fill='x', pady=5)
    
    def create_results_tab(self):
        """Create results tab"""
        results_frame = ttk.Frame(self.notebook)
        self.notebook.add(results_frame, text="Results")
        
        # Results summary
        summary_frame = ttk.LabelFrame(results_frame, text="Sync Summary", padding="10")
        summary_frame.pack(fill='x', padx=10, pady=10)
        
        self.results_summary = tk.Label(summary_frame, text="No sync performed yet", 
                                       font=("Arial", 11), justify="left")
        self.results_summary.pack(anchor='w')
        
        # Results tree
        tree_frame = ttk.LabelFrame(results_frame, text="Detailed Results", padding="10")
        tree_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
        
        columns = ('Rally ID', 'Action', 'Jira Issue', 'Status Change', 'Message')
        self.results_tree = ttk.Treeview(tree_frame, columns=columns, show='headings', height=10)
        
        # Configure columns
        self.results_tree.column('Rally ID', width=100)
        self.results_tree.column('Action', width=120)
        self.results_tree.column('Jira Issue', width=100)
        self.results_tree.column('Status Change', width=150)
        self.results_tree.column('Message', width=300)
        
        for col in columns:
            self.results_tree.heading(col, text=col)
        
        # Scrollbar for results
        results_scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=self.results_tree.yview)
        self.results_tree.configure(yscrollcommand=results_scrollbar.set)
        
        self.results_tree.pack(side='left', fill='both', expand=True)
        results_scrollbar.pack(side='right', fill='y')
        
        # Export button
        export_button = tk.Button(results_frame, text="📊 Export Results", command=self.export_results,
                                 bg="#3498DB", fg="white", font=("Arial", 10))
        export_button.pack(pady=10)
    
    def create_logging_tab(self):
        """Create logging tab"""
        logging_frame = ttk.Frame(self.notebook)
        self.notebook.add(logging_frame, text="Logs")
        
        # Log display
        self.log_text = scrolledtext.ScrolledText(logging_frame, wrap=tk.WORD, height=15)
        self.log_text.pack(fill='both', expand=True, padx=10, pady=10)
        
        # Log controls
        log_controls = tk.Frame(logging_frame)
        log_controls.pack(fill='x', padx=10, pady=(0, 10))
        
        tk.Button(log_controls, text="Clear Logs", command=self.clear_logs,
                 bg="#E67E22", fg="white", font=("Arial", 9)).pack(side='left')
        tk.Button(log_controls, text="Save Logs", command=self.save_logs,
                 bg="#3498DB", fg="white", font=("Arial", 9)).pack(side='left', padx=(10, 0))
    
    def update_mappings_display(self):
        """Update the mappings tree display"""
        # Clear existing items
        for item in self.mappings_tree.get_children():
            self.mappings_tree.delete(item)
        
        # Add current mappings
        if isinstance(self.status_mappings, dict):
            # Check if it's the new format with artifact types
            if any(isinstance(v, dict) for v in self.status_mappings.values()):
                # New format: artifact-type-specific mappings
                for artifact_type, mappings in self.status_mappings.items():
                    if isinstance(mappings, dict):
                        for jira_status, rally_status in mappings.items():
                            self.mappings_tree.insert('', 'end', values=(artifact_type.title(), jira_status, rally_status))
            else:
                # Old format: simple mappings
                for jira_status, rally_status in self.status_mappings.items():
                    self.mappings_tree.insert('', 'end', values=('All', jira_status, rally_status))
    
    def load_default_mappings(self):
        """Load default status mappings"""
        self.status_mappings = DEFAULT_STATUS_MAPPINGS.copy()
        self.update_mappings_display()
        self.log_message("✅ Loaded default status mappings")
        messagebox.showinfo("Success", "Loaded default status mappings")
    
    def load_mappings_file(self):
        """Load status mappings from file"""
        filename = filedialog.askopenfilename(
            title="Load Status Mappings",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")]
        )
        if filename:
            try:
                with open(filename, 'r') as f:
                    self.status_mappings = json.load(f)
                self.update_mappings_display()
                self.log_message(f"✅ Loaded status mappings from {filename}")
                messagebox.showinfo("Success", f"Loaded {len(self.status_mappings)} mappings from file")
            except Exception as e:
                self.log_message(f"❌ Error loading mappings: {e}")
                messagebox.showerror("Error", f"Error loading mappings: {e}")
    
    def save_mappings_file(self):
        """Save status mappings to file"""
        filename = filedialog.asksaveasfilename(
            title="Save Status Mappings",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialvalue="status_mappings.json"
        )
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(self.status_mappings, f, indent=2)
                self.log_message(f"✅ Saved status mappings to {filename}")
                messagebox.showinfo("Success", f"Saved status mappings to {filename}")
            except Exception as e:
                self.log_message(f"❌ Error saving mappings: {e}")
                messagebox.showerror("Error", f"Error saving mappings: {e}")
    
    def test_connections(self):
        """Test connections to Jira and Rally"""
        def test_in_thread():
            try:
                self.sync_button.config(state='disabled')
                self.progress_var.set("Testing connections...")
                
                sync_tool = RallyJiraReverseSync(
                    jira_url=self.jira_url_var.get().strip(),
                    jira_user=self.jira_user_var.get().strip(),
                    jira_token=self.jira_token_var.get().strip(),
                    jira_project=self.jira_project_var.get().strip(),
                    rally_url=self.rally_url_var.get().strip(),
                    rally_api_key=self.rally_api_key_var.get().strip(),
                    rally_workspace=self.rally_workspace_var.get().strip(),
                    rally_project=self.rally_project_var.get().strip(),
                    status_mappings=self.status_mappings
                )
                
                # Test Jira
                jira_success, jira_msg = sync_tool.connect_to_jira()
                self.log_message(f"Jira Test: {jira_msg}")
                
                # Test Rally
                rally_success, rally_msg = sync_tool.connect_to_rally()
                self.log_message(f"Rally Test: {rally_msg}")
                
                self.progress_var.set("Connection test completed")
                
                if jira_success and rally_success:
                    messagebox.showinfo("Success", "✅ Both connections successful!")
                else:
                    error_msg = ""
                    if not jira_success:
                        error_msg += f"Jira: {jira_msg}\n"
                    if not rally_success:
                        error_msg += f"Rally: {rally_msg}"
                    messagebox.showerror("Connection Error", error_msg)
                
            except Exception as e:
                self.log_message(f"❌ Connection test error: {e}")
                messagebox.showerror("Error", f"Connection test failed: {e}")
            finally:
                self.sync_button.config(state='normal')
        
        threading.Thread(target=test_in_thread, daemon=True).start()
    
    def lookup_jira_issue(self):
        """Lookup a single JIRA issue and show corresponding Rally item status"""
        jira_key = self.jira_key_var.get().strip().upper()
        if not jira_key:
            messagebox.showwarning("Input Required", "Please enter a JIRA issue key")
            return
        
        # Validate configuration
        if not all([self.jira_url_var.get().strip(), self.jira_user_var.get().strip(),
                   self.jira_token_var.get().strip(), self.jira_project_var.get().strip(),
                   self.rally_api_key_var.get().strip(), self.rally_workspace_var.get().strip(),
                   self.rally_project_var.get().strip()]):
            messagebox.showerror("Configuration Error", 
                               "Please fill in all required configuration fields first")
            return
        
        def lookup_in_thread():
            try:
                self.lookup_button.config(state='disabled')
                self.lookup_results.config(state='normal')
                self.lookup_results.delete('1.0', 'end')
                self.lookup_results.insert('1.0', f"🔍 Looking up JIRA issue: {jira_key}...\n\n")
                self.lookup_results.config(state='disabled')
                self.lookup_results.update()
                
                # Create sync tool
                sync_tool = RallyJiraReverseSync(
                    jira_url=self.jira_url_var.get().strip(),
                    jira_user=self.jira_user_var.get().strip(),
                    jira_token=self.jira_token_var.get().strip(),
                    jira_project=self.jira_project_var.get().strip(),
                    rally_url=self.rally_url_var.get().strip(),
                    rally_api_key=self.rally_api_key_var.get().strip(),
                    rally_workspace=self.rally_workspace_var.get().strip(),
                    rally_project=self.rally_project_var.get().strip(),
                    status_mappings=self.status_mappings
                )
                
                # Test connections
                jira_success, jira_msg = sync_tool.connect_to_jira()
                if not jira_success:
                    raise Exception(f"JIRA connection failed: {jira_msg}")
                
                rally_success, rally_msg = sync_tool.connect_to_rally()
                if not rally_success:
                    raise Exception(f"Rally connection failed: {rally_msg}")
                
                # Get JIRA issue
                try:
                    jira_issue = sync_tool.jira_client.issue(jira_key)
                    jira_status = jira_issue.fields.status.name
                    jira_summary = jira_issue.fields.summary
                    
                    result_text = f"✅ JIRA Issue Found:\n"
                    result_text += f"   Key: {jira_key}\n"
                    result_text += f"   Summary: {jira_summary}\n"
                    result_text += f"   Status: {jira_status}\n\n"
                    
                except Exception as e:
                    result_text = f"❌ JIRA Issue Not Found: {jira_key}\n"
                    result_text += f"   Error: {str(e)}\n\n"
                    self.update_lookup_results(result_text)
                    return
                
                # Search for Rally items that reference this JIRA issue
                rally_items_found = []
                for item_type in ['HierarchicalRequirement', 'Defect', 'Task']:
                    try:
                        # Search Rally for items containing the JIRA key
                        query_filter = f'((Name contains "{jira_key}") OR (Description contains "{jira_key}"))'
                        
                        response = sync_tool.rally_client.get(item_type, 
                                                            fetch="FormattedID,Name,State,ScheduleState,Description",
                                                            query=query_filter,
                                                            project=sync_tool.rally_project)
                        
                        for item in response:
                            # Double-check that the item actually contains the JIRA key
                            name = getattr(item, 'Name', '') or ''
                            description = getattr(item, 'Description', '') or ''
                            
                            if jira_key in name or jira_key in description:
                                current_status = getattr(item, 'State', None) or getattr(item, 'ScheduleState', None)
                                rally_items_found.append({
                                    'type': item_type,
                                    'id': item.FormattedID,
                                    'name': name,
                                    'current_status': str(current_status) if current_status else 'Unknown',
                                    'description': description[:100] + '...' if len(description) > 100 else description
                                })
                                
                    except Exception as e:
                        result_text += f"⚠️ Error searching {item_type}: {str(e)}\n"
                
                if rally_items_found:
                    result_text += f"🎯 Related Rally Items Found ({len(rally_items_found)}):\n\n"
                    
                    for item in rally_items_found:
                        new_status = self.status_mappings.get(jira_status, jira_status)
                        result_text += f"   📋 {item['type']}: {item['id']}\n"
                        result_text += f"      Name: {item['name']}\n"
                        result_text += f"      Current Status: {item['current_status']}\n"
                        result_text += f"      Would Update To: {new_status}\n"
                        
                        if item['current_status'] == new_status:
                            result_text += f"      ✅ Already up to date!\n"
                        else:
                            result_text += f"      🔄 Status change needed\n"
                        result_text += "\n"
                else:
                    result_text += "ℹ️ No Rally items found that reference this JIRA issue.\n"
                    result_text += "   This JIRA issue may not be linked to any Rally work items.\n"
                
                self.update_lookup_results(result_text)
                
            except Exception as e:
                error_text = f"❌ Lookup failed: {str(e)}\n\n"
                error_text += "Please check your configuration and try again."
                self.update_lookup_results(error_text)
            finally:
                self.lookup_button.config(state='normal')
        
        threading.Thread(target=lookup_in_thread, daemon=True).start()
    
    def update_lookup_results(self, text):
        """Update lookup results display"""
        def update_ui():
            self.lookup_results.config(state='normal')
            self.lookup_results.delete('1.0', 'end')
            self.lookup_results.insert('1.0', text)
            self.lookup_results.config(state='disabled')
        
        self.root.after(0, update_ui)
    
    def update_rally_lookup_results(self, text):
        """Update Rally lookup results display"""
        def update_ui():
            self.rally_lookup_results.config(state='normal')
            self.rally_lookup_results.delete('1.0', 'end')
            self.rally_lookup_results.insert('1.0', text)
            self.rally_lookup_results.config(state='disabled')
        
        self.root.after(0, update_ui)
    
    def lookup_rally_to_jira(self):
        """Lookup Rally ID, extract JIRA key from name, and find corresponding JIRA issue"""
        rally_id = self.rally_id_var.get().strip().upper()
        if not rally_id:
            messagebox.showwarning("Input Required", "Please enter a Rally ID")
            return
        
        # Validate configuration
        if not all([self.jira_url_var.get().strip(), self.jira_user_var.get().strip(),
                   self.jira_token_var.get().strip(), self.jira_project_var.get().strip(),
                   self.rally_api_key_var.get().strip(), self.rally_workspace_var.get().strip(),
                   self.rally_project_var.get().strip()]):
            messagebox.showerror("Configuration Error", 
                               "Please fill in all required configuration fields first")
            return
        
        def lookup_in_thread():
            try:
                self.rally_lookup_button.config(state='disabled')
                self.rally_lookup_results.config(state='normal')
                self.rally_lookup_results.delete('1.0', 'end')
                self.rally_lookup_results.insert('1.0', f"🎯 Looking up Rally ID: {rally_id} and extracting JIRA key from name...\n\n")
                self.rally_lookup_results.config(state='disabled')
                self.rally_lookup_results.update()
                
                # Create sync tool
                sync_tool = RallyJiraReverseSync(
                    jira_url=self.jira_url_var.get().strip(),
                    jira_user=self.jira_user_var.get().strip(),
                    jira_token=self.jira_token_var.get().strip(),
                    jira_project=self.jira_project_var.get().strip(),
                    rally_url=self.rally_url_var.get().strip(),
                    rally_api_key=self.rally_api_key_var.get().strip(),
                    rally_workspace=self.rally_workspace_var.get().strip(),
                    rally_project=self.rally_project_var.get().strip(),
                    status_mappings=self.status_mappings
                )
                
                # Test connections
                jira_success, jira_msg = sync_tool.connect_to_jira()
                if not jira_success:
                    raise Exception(f"JIRA connection failed: {jira_msg}")
                
                rally_success, rally_msg = sync_tool.connect_to_rally()
                if not rally_success:
                    raise Exception(f"Rally connection failed: {rally_msg}")
                
                # Find the Rally item by FormattedID
                rally_item_info = None
                
                # Use the EXACT same logic as working get_single_rally_item method
                # Determine item type from FormattedID prefix first (more efficient)
                item_type_map = {
                    'US': 'hierarchicalrequirement',
                    'DE': 'defect', 
                    'TA': 'task',
                    'TC': 'testcase'
                }
                
                prefix = rally_id[:2].upper() if len(rally_id) >= 2 else rally_id[:1].upper()
                item_type = item_type_map.get(prefix, 'hierarchicalrequirement')
                
                sync_tool.logger.info(f"🔍 Searching for Rally ID: {rally_id} (type: {item_type}) in project: {sync_tool.rally_project}")
                
                # Use the EXACT same query logic as working get_single_rally_item
                project_is_objectid = sync_tool.rally_project.isdigit()
                
                if project_is_objectid:
                    # Use ObjectID reference (same as working bulk fetch)
                    project_criteria = f'(Project.ObjectID = {sync_tool.rally_project})'
                else:
                    # Escape project name for Rally query - handle special characters
                    escaped_project = sync_tool.rally_project.replace('|', '\\\\|')
                    project_criteria = f'(Project.Name = "{escaped_project}")'
                
                # Use FormattedID-only query - workspace parameter constrains to correct project
                # This avoids Rally's AND syntax parsing issues
                query_criteria = f'(FormattedID = "{rally_id}")'
                
                sync_tool.logger.debug(f"Rally single item query: {query_criteria}")
                
                # Search only the determined item type (more efficient)
                for item_type_name in [item_type]:
                    try:
                        # Use the EXACT same URL structure as working bulk fetch
                        url = f"{sync_tool.rally_base_url}/{item_type_name.lower()}"
                        params = {
                            'query': query_criteria,
                            'fetch': 'FormattedID,Name,Description,State,ScheduleState,ObjectID,Project,Workspace',
                            'pagesize': 1  # Only need 1 item
                        }
                        
                        # Add workspace parameter if available (EXACT same as working bulk fetch)
                        if hasattr(sync_tool, 'rally_workspace') and sync_tool.rally_workspace:
                            if sync_tool.rally_workspace.isdigit():
                                params['workspace'] = f'/workspace/{sync_tool.rally_workspace}'
                        
                        sync_tool.logger.debug(f"Rally single item URL: {url}")
                        sync_tool.logger.debug(f"Rally single item params: {params}")
                        
                        response = requests.get(url, headers=sync_tool.rally_auth_headers, params=params, timeout=30)
                        
                        if response.status_code != 200:
                            error_details = f"Status: {response.status_code}, Response: {response.text[:300]}"
                            sync_tool.logger.error(f"Failed to fetch Rally item {rally_id}: {error_details}")
                            continue
                        
                        try:
                            data = response.json()
                        except json.JSONDecodeError as e:
                            sync_tool.logger.error(f"Rally API returned invalid JSON for {item_type_name}: {e}")
                            continue
                        
                        query_result = data.get('QueryResult', {})
                        results = query_result.get('Results', [])
                        total_count = query_result.get('TotalResultCount', 0)
                        errors = query_result.get('Errors', [])
                        
                        if errors:
                            sync_tool.logger.error(f"Rally query errors for {item_type_name}: {errors}")
                            continue
                        
                        sync_tool.logger.info(f"Rally single item API returned {len(results)} of {total_count} results for {rally_id}")
                        
                        if results:
                            # Process the found item (same as working bulk fetch)
                            item = results[0]
                            state_value = item.get('State') or item.get('ScheduleState')
                            
                            rally_item_info = {
                                'type': item_type_name,
                                'formatted_id': item.get('FormattedID'),
                                'name': item.get('Name'),
                                'description': item.get('Description', ''),
                                'status': state_value,
                                'project': item.get('Project', {}).get('_refObjectName', 'Unknown'),
                                'workspace': item.get('Workspace', {}).get('_refObjectName', 'Unknown'),
                                'object_id': item.get('ObjectID'),
                                'ref': item.get('_ref')
                            }
                            sync_tool.logger.info(f"Successfully fetched Rally item: {rally_id} - {item.get('Name', 'N/A')[:60]}")
                            break
                            
                    except requests.RequestException as e:
                        sync_tool.logger.error(f"Network error querying Rally {item_type_name}: {e}")
                        continue
                    except Exception as e:
                        sync_tool.logger.error(f"Unexpected error querying Rally {item_type_name}: {e}")
                        continue
                
                result_text = ""
                
                if not rally_item_info:
                    result_text = f"❌ Rally Item Not Found: {rally_id}\n"
                    result_text += f"   Project: {sync_tool.rally_project}\n"
                    result_text += f"   Workspace: {sync_tool.rally_workspace}\n\n"
                    result_text += "🔍 Troubleshooting:\n"
                    result_text += "   • Verify the Rally ID format (e.g., US123, DE456, TA789)\n"
                    result_text += "   • Check if item exists in the specified project\n"
                    result_text += "   • Ensure you have access to the Rally workspace/project\n"
                    result_text += "   • Try searching without project filter in Rally web interface\n\n"
                    result_text += "💡 Tips:\n"
                    result_text += "   • Rally IDs are case-sensitive\n"
                    result_text += "   • Use FormattedID (not ObjectID) for lookup\n"
                    result_text += "   • Check the Logs tab for detailed error messages\n"
                    
                    # Log the failed lookup details for debugging
                    sync_tool.logger.warning(f"Rally item {rally_id} not found in project {sync_tool.rally_project}")
                    sync_tool.logger.debug(f"Search criteria: FormattedID = '{rally_id}' in project '{sync_tool.rally_project}'")
                    
                    self.update_rally_lookup_results(result_text)
                    return
                
                result_text += f"✅ Rally Item Found:\n"
                result_text += f"   ID: {rally_item_info['formatted_id']}\n"
                result_text += f"   Type: {rally_item_info['type']}\n"  
                result_text += f"   Name: {rally_item_info['name']}\n"
                result_text += f"   Current Status: {rally_item_info['status']}\n"
                result_text += f"   Project: {rally_item_info['project']}\n\n"
                
                # Extract JIRA key from Rally item name using pattern matching
                # Supports patterns like: "JIRA|Bug|CAM-2268|Description" or direct mentions like "CAM-2268"
                jira_keys = []
                
                sync_tool.logger.info(f"🔍 Extracting JIRA keys from Rally item: {rally_item_info['formatted_id']}")
                sync_tool.logger.debug(f"Rally item name: '{rally_item_info['name']}'")
                if rally_item_info['description']:
                    sync_tool.logger.debug(f"Rally item description length: {len(rally_item_info['description'])} characters")
                
                # Pattern 1: JIRA|Type|KEY|Description format (case insensitive)
                pattern1 = r'JIRA\|[^|]*\|([A-Z]+-\d+)\|'
                
                # Pattern 2: Direct JIRA key mentions like CAM-2268, PROJ-123 (more comprehensive)
                pattern2 = r'\b([A-Z]{2,10}-\d+)\b'
                
                # Pattern 3: Alternative formats like [CAM-1234] or (CAM-1234)
                pattern3 = r'[\[\(]([A-Z]{2,10}-\d+)[\]\)]'
                
                name_text = rally_item_info['name'] or ''
                desc_text = rally_item_info['description'] or ''
                
                # Search in Rally item name
                matches1 = re.findall(pattern1, name_text, re.IGNORECASE)
                matches2 = re.findall(pattern2, name_text, re.IGNORECASE) 
                matches3 = re.findall(pattern3, name_text, re.IGNORECASE)
                
                jira_keys.extend([m.upper() for m in matches1])
                jira_keys.extend([m.upper() for m in matches2])
                jira_keys.extend([m.upper() for m in matches3])
                
                sync_tool.logger.debug(f"Found in name - Pattern 1: {matches1}, Pattern 2: {matches2}, Pattern 3: {matches3}")
                
                # Search in description if available
                if desc_text:
                    desc_matches1 = re.findall(pattern1, desc_text, re.IGNORECASE)
                    desc_matches2 = re.findall(pattern2, desc_text, re.IGNORECASE)
                    desc_matches3 = re.findall(pattern3, desc_text, re.IGNORECASE)
                    
                    jira_keys.extend([m.upper() for m in desc_matches1])
                    jira_keys.extend([m.upper() for m in desc_matches2])
                    jira_keys.extend([m.upper() for m in desc_matches3])
                    
                    sync_tool.logger.debug(f"Found in description - Pattern 1: {desc_matches1}, Pattern 2: {desc_matches2}, Pattern 3: {desc_matches3}")
                
                # Remove duplicates while preserving order
                unique_jira_keys = list(dict.fromkeys(jira_keys))
                
                sync_tool.logger.info(f"📋 Extracted JIRA keys: {unique_jira_keys if unique_jira_keys else 'None found'}")
                
                if not unique_jira_keys:
                    result_text += "⚠️ No JIRA keys found in Rally item name or description\n\n"
                    result_text += "   Searched for patterns like:\n"
                    result_text += "   • JIRA|Bug|CAM-2268|Description\n"
                    result_text += "   • Direct mentions like CAM-2268, PROJ-123\n"
                    result_text += "   • Bracketed format like [CAM-2268] or (CAM-2268)\n\n"
                    result_text += "🔍 Debug Information:\n"
                    result_text += f"   • Rally name: '{rally_item_info['name']}'\n"
                    result_text += f"   • Description length: {len(rally_item_info.get('description', ''))} characters\n"
                    result_text += f"   • Check the Logs tab for detailed pattern matching results\n\n"
                    result_text += "💡 To enable mapping:\n"
                    result_text += "   1. Update Rally item name to include JIRA key\n"
                    result_text += f"   2. Example: 'JIRA|Bug|CAM-2268|{rally_item_info['name'][:30]}...'\n"
                    result_text += "   3. Or add JIRA key directly: 'CAM-2268 - {rally_item_info['name'][:30]}...'\n"
                    result_text += "   4. Re-run this lookup\n"
                    self.update_rally_lookup_results(result_text)
                    return
                
                result_text += f"🎯 Extracted JIRA Key(s): {', '.join(unique_jira_keys)}\n\n"
                
                # Fetch each JIRA issue
                jira_issues = []
                jira_errors = []
                
                for jira_key in unique_jira_keys:
                    try:
                        sync_tool.logger.info(f"🔍 Looking up JIRA issue: {jira_key}")
                        issue = sync_tool.jira_client.issue(jira_key)
                        jira_issues.append({
                            'key': issue.key,
                            'summary': issue.fields.summary,
                            'status': issue.fields.status.name,
                            'issue_type': issue.fields.issuetype.name,
                            'project': issue.fields.project.key,
                            'assignee': issue.fields.assignee.displayName if issue.fields.assignee else 'Unassigned'
                        })
                        sync_tool.logger.info(f"✅ Found JIRA issue: {jira_key} - {issue.fields.summary[:50]}")
                        
                    except Exception as e:
                        error_msg = str(e).lower()
                        if 'does not exist' in error_msg or '404' in error_msg:
                            detailed_error = f"{jira_key} does not exist or you don't have access"
                        elif 'unauthorized' in error_msg or '401' in error_msg:
                            detailed_error = f"{jira_key} - Authentication failed, check JIRA credentials"
                        elif 'forbidden' in error_msg or '403' in error_msg:
                            detailed_error = f"{jira_key} - Access forbidden, check JIRA permissions"
                        elif 'timeout' in error_msg:
                            detailed_error = f"{jira_key} - Request timeout, try again"
                        else:
                            detailed_error = f"{jira_key} - {str(e)}"
                        
                        jira_errors.append(detailed_error)
                        sync_tool.logger.warning(f"❌ JIRA lookup failed: {detailed_error}")
                        
                # Show any JIRA errors that occurred
                if jira_errors:
                    result_text += f"❌ JIRA Lookup Issues ({len(jira_errors)}):\n"
                    for error in jira_errors:
                        result_text += f"   • {error}\n"
                    result_text += "\n"
                
                if jira_issues:
                    result_text += f"📋 Found {len(jira_issues)} JIRA Issue(s):\n\n"
                    
                    for i, issue in enumerate(jira_issues, 1):
                        result_text += f"   {i}. {issue['key']} ({issue['project']})\n"
                        result_text += f"      Summary: {issue['summary']}\n"
                        result_text += f"      Type: {issue['issue_type']}\n"
                        result_text += f"      Status: {issue['status']}\n"
                        result_text += f"      Assignee: {issue['assignee']}\n"
                        
                        # Show what the Rally status would be mapped to
                        target_rally_status = self.status_mappings.get(issue['status'], issue['status'])
                        current_rally_status = rally_item_info['status']
                        
                        if current_rally_status == target_rally_status:
                            result_text += f"      Rally Update: ✅ Already synced ({target_rally_status})\n"
                        else:
                            result_text += f"      Rally Update: 🔄 Would change {current_rally_status} → {target_rally_status}\n"
                        
                        result_text += "\n"
                    
                    # Show direct mapping summary
                    result_text += "🎯 Direct Mapping Summary:\n"
                    if len(jira_issues) == 1:
                        primary_issue = jira_issues[0]
                        result_text += f"   Rally {rally_id} ↔ JIRA {primary_issue['key']}\n"
                        result_text += f"   Status: {primary_issue['status']} (JIRA) → {self.status_mappings.get(primary_issue['status'], primary_issue['status'])} (Rally)\n\n"
                        
                        # Ask if user wants to update
                        target_status = self.status_mappings.get(primary_issue['status'], primary_issue['status'])
                        if rally_item_info['status'] != target_status:
                            result_text += "💡 Quick Update Available:\n"
                            result_text += f"   Click the full sync to update {rally_id} from {rally_item_info['status']} to {target_status}\n"
                            result_text += "   Or use the main sync with filter: (FormattedID = \"{}\")".format(rally_id)
                    else:
                        result_text += f"   Rally {rally_id} maps to multiple JIRA issues\n"
                        result_text += "   Consider which JIRA status should take priority\n"
                        
                        # Show priority suggestion
                        statuses = [issue['status'] for issue in jira_issues]
                        if 'In Progress' in statuses:
                            result_text += "   📌 Suggestion: Use 'In Progress' status (work is active)\n"
                        elif 'Done' in statuses or 'Closed' in statuses:
                            result_text += "   📌 Suggestion: Use 'Done/Closed' status (work is complete)\n"
                
                else:
                    result_text += "❌ No valid JIRA issues found for extracted keys\n"
                    result_text += "   Check if the JIRA keys exist and are accessible\n"
                
                self.update_rally_lookup_results(result_text)
                
            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e).lower()
                
                sync_tool.logger.error(f"Rally to JIRA lookup failed: {error_type} - {e}")
                
                error_text = f"❌ Rally to JIRA lookup failed: {error_type}\n\n"
                
                # Provide specific guidance based on error type
                if 'connection' in error_msg or 'timeout' in error_msg:
                    error_text += "🌐 Network Issue:\n"
                    error_text += "   • Check your internet connection\n"
                    error_text += "   • Verify Rally/JIRA URLs are accessible\n"
                    error_text += "   • Try again in a few moments\n\n"
                elif 'authentication' in error_msg or '401' in error_msg:
                    error_text += "🔐 Authentication Issue:\n"
                    error_text += "   • Check Rally API Key is valid\n"
                    error_text += "   • Check JIRA credentials (email/token)\n"
                    error_text += "   • Verify credentials haven't expired\n\n"
                elif 'permission' in error_msg or 'forbidden' in error_msg or '403' in error_msg:
                    error_text += "🚫 Permission Issue:\n"
                    error_text += "   • Check Rally workspace/project access\n"
                    error_text += "   • Verify JIRA project permissions\n"
                    error_text += "   • Contact your admin if needed\n\n"
                else:
                    error_text += f"🔧 Technical Details:\n"
                    error_text += f"   • Error: {str(e)}\n"
                    error_text += "   • Check the Logs tab for more details\n\n"
                
                error_text += "💡 Next Steps:\n"
                error_text += "   1. Review the error details above\n"
                error_text += "   2. Check your configuration in the Configuration tab\n"
                error_text += "   3. Test connections using 'Test Connections' button\n"
                error_text += "   4. Check the Logs tab for detailed error information\n"
                
                self.update_rally_lookup_results(error_text)
            finally:
                self.rally_lookup_button.config(state='normal')
        
        threading.Thread(target=lookup_in_thread, daemon=True).start()
    
    def start_sync(self):
        """Start the sync process"""
        # Validate input
        if not all([self.jira_url_var.get().strip(), self.jira_user_var.get().strip(),
                   self.jira_token_var.get().strip(), self.rally_api_key_var.get().strip(),
                   self.rally_workspace_var.get().strip(), self.rally_project_var.get().strip()]):
            messagebox.showerror("Configuration Error", 
                               "Please fill in all required configuration fields")
            return
        
        # Get selected item types
        item_types = []
        if self.sync_user_stories.get():
            item_types.append('HierarchicalRequirement')
        if self.sync_defects.get():
            item_types.append('Defect')
        if self.sync_tasks.get():
            item_types.append('Task')
        
        if not item_types:
            messagebox.showerror("Selection Error", "Please select at least one Rally item type to sync")
            return
        
        # Check for existing checkpoint for resumable sync
        resume_from_checkpoint = False
        if self.sync_mode_var.get() == "cam_references":
            # Create a temporary sync tool to check for checkpoints
            temp_sync_tool = RallyJiraReverseSync(
                jira_url=self.jira_url_var.get().strip(),
                jira_user=self.jira_user_var.get().strip(),
                jira_token=self.jira_token_var.get().strip(),
                jira_project=self.jira_project_var.get().strip(),
                rally_url=self.rally_url_var.get().strip(),
                rally_api_key=self.rally_api_key_var.get().strip(),
                rally_workspace=self.rally_workspace_var.get().strip(),
                rally_project=self.rally_project_var.get().strip(),
                status_mappings=self.status_mappings
            )
            
            # Check for existing checkpoint
            sync_config = {
                'item_types': sorted(item_types),
                'rally_filter': self.rally_filter_var.get().strip() or "",
                'rally_project': self.rally_project_var.get().strip(),
                'rally_workspace': self.rally_workspace_var.get().strip(),
                'jira_project': self.jira_project_var.get().strip(),
                'sync_mode': 'cam_references'
            }
            
            checkpoint_data, checkpoint_msg = temp_sync_tool.checkpoint_manager.load_checkpoint(sync_config)
            if checkpoint_data:
                processed_count = len(checkpoint_data.get('processed_items', []))
                total_items = checkpoint_data.get('total_items', 0)
                
                # Show resume dialog
                resume_message = f"🔄 Resume Previous Sync?\n\n"
                resume_message += f"{checkpoint_msg}\n\n"
                resume_message += f"Progress: {processed_count}/{total_items} items processed\n"
                resume_message += f"Remaining: {total_items - processed_count} items\n\n"
                resume_message += "Do you want to:\n"
                resume_message += "• YES = Resume from where it stopped\n"
                resume_message += "• NO = Start fresh (current checkpoint will be cleared)"
                
                resume_choice = messagebox.askyesnocancel("Resume Sync", resume_message)
                
                if resume_choice is None:  # User clicked Cancel
                    return
                elif resume_choice:  # User clicked Yes - Resume
                    resume_from_checkpoint = True
                    self.log_message(f"🔄 Resuming sync from checkpoint - {processed_count} items already processed")
                else:  # User clicked No - Start fresh
                    # Clear the existing checkpoint
                    temp_sync_tool.checkpoint_manager.delete_checkpoint(sync_config)
                    self.log_message("🆕 Starting fresh sync - previous checkpoint cleared")
        
        # Clear previous results
        for item in self.results_tree.get_children():
            self.results_tree.delete(item)
        
        # Start sync thread with checkpoint info
        self.stop_sync = False
        self.sync_thread = threading.Thread(
            target=self.sync_worker,
            args=(item_types, self.rally_filter_var.get().strip(), self.dry_run_var.get(), resume_from_checkpoint),
            daemon=True
        )
        self.sync_thread.start()
        
        # Update UI
        self.sync_button.config(state='disabled')
        self.stop_button.config(state='normal')
        self.progress_bar['value'] = 0
        
        # Switch to Results tab
        self.notebook.select(2)
    
    def sync_worker(self, item_types: List[str], rally_filter: str, dry_run: bool, resume_from_checkpoint: bool = False):
        """Worker thread for sync process"""
        try:
            sync_mode = self.sync_mode_var.get()
            
            if sync_mode == "cam_references":
                self.log_message("🎯 Starting CAM-xxx Reference Sync Mode...")
                self.log_message("   Extracting JIRA keys from Rally item names and syncing with those JIRA tickets...")
                if resume_from_checkpoint:
                    self.log_message("🔄 Resuming from previous checkpoint...")
            else:
                self.log_message("🔍 Starting Rally ID Search Mode...")
                self.log_message("   Searching JIRA for Rally IDs and syncing status...")
            
            # Create sync tool
            sync_tool = RallyJiraReverseSync(
                jira_url=self.jira_url_var.get().strip(),
                jira_user=self.jira_user_var.get().strip(),
                jira_token=self.jira_token_var.get().strip(),
                jira_project=self.jira_project_var.get().strip(),
                rally_url=self.rally_url_var.get().strip(),
                rally_api_key=self.rally_api_key_var.get().strip(),
                rally_workspace=self.rally_workspace_var.get().strip(),
                rally_project=self.rally_project_var.get().strip(),
                status_mappings=self.status_mappings
            )
            
            # Create enhanced progress callback that also logs detailed info
            def enhanced_progress_callback(percentage, message):
                self.update_progress(percentage, message)
                if "Found" in message and "Rally items" in message:
                    self.log_message(f"📋 {message}")
                elif "JIRA keys in" in message:
                    self.log_message(f"🎯 {message}")
                elif "Rally" in message and "JIRA" in message and "->" in message:
                    self.log_message(f"📊 {message}")
                elif "Skipped" in message and "already processed" in message:
                    self.log_message(f"⏭️  {message}")
                elif "Resuming" in message or "checkpoint" in message.lower():
                    self.log_message(f"🔄 {message}")
            
            # Start sync using the appropriate method
            if sync_mode == "cam_references":
                self.log_message(f"🔍 Fetching Rally items: {', '.join(item_types)}")
                self.log_message(f"📍 Rally Project: {self.rally_project_var.get()}")
                if rally_filter:
                    self.log_message(f"🔎 Rally Filter: {rally_filter}")
                
                # Use resumable version for cam_references mode
                results = sync_tool.sync_rally_with_jira_cam_references_resumable(
                    item_types=item_types,
                    rally_filter=rally_filter if rally_filter else None,
                    dry_run=dry_run,
                    progress_callback=enhanced_progress_callback,
                    enable_checkpoints=True,
                    resume_from_checkpoint=resume_from_checkpoint
                )
                
                # Add detailed result logging for CAM mode
                self.log_message(f"📊 Found {results['total_rally_items']} Rally items")
                self.log_message(f"🎯 {results['rally_items_with_jira_refs']} items had JIRA references")
                self.log_message(f"✅ {results['jira_tickets_found']} JIRA tickets found")
                self.log_message(f"🔄 {results['successful_updates']} items {'would be updated' if dry_run else 'updated'}")
                if results['errors'] > 0:
                    self.log_message(f"❌ {results['errors']} errors occurred")
                
                # Log checkpoint information if available
                if results.get('resumed_from_checkpoint'):
                    self.log_message(f"🔄 Resumed from checkpoint: {results.get('checkpoint_info', 'N/A')}")
                
                # Log successful completion without errors
                if results['errors'] == 0:
                    self.log_message("✅ Sync completed successfully! All checkpoints have been cleaned up.")
                    
            else:
                # Use original function for rally ID search mode (no checkpoint support yet)
                results = sync_tool.sync_rally_to_jira(
                    item_types=item_types,
                    rally_filter=rally_filter if rally_filter else None,
                    dry_run=dry_run,
                    progress_callback=self.update_progress
                )
            
            # Update results
            self.root.after(0, self.display_results, results)
            
        except Exception as e:
            error_msg = f"❌ Sync error: {str(e)}"
            self.log_message(error_msg)
            self.log_message("🔄 Progress has been saved in checkpoint - you can resume this sync later")
            self.root.after(0, lambda: messagebox.showerror("Sync Error", 
                f"{error_msg}\n\nYour progress has been saved. You can resume this sync by clicking 'Start Sync' again."))
        finally:
            self.root.after(0, self.sync_completed)
    
    def update_progress(self, percentage: float, message: str):
        """Update progress bar and message"""
        def update_ui():
            if not self.stop_sync:  # Only update if not stopped
                self.progress_var.set(message)
                self.progress_bar['value'] = percentage
                self.log_message(f"Progress: {message}")
        
        self.root.after(0, update_ui)
    
    def display_results(self, results: Dict):
        """Display sync results"""
        try:
            # Detect sync mode based on result structure and build appropriate summary
            is_cam_mode = 'rally_items_with_jira_refs' in results
            
            if is_cam_mode:
                summary_text = f"""📊 CAM-xxx Reference Sync Results:
• Total Rally Items: {results['total_rally_items']}
• Rally Items with JIRA References: {results['rally_items_with_jira_refs']}
• JIRA Tickets Found: {results['jira_tickets_found']}
• Successful Updates: {results['successful_updates']}
• Errors: {results['errors']}

Completion Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            else:
                summary_text = f"""📊 Rally ID Search Sync Results:
• Total Rally Items: {results['total_rally_items']}
• Jira Matches Found: {results['jira_matches_found']}
• Successful Updates: {results['successful_updates']}
• Errors: {results['errors']}

Completion Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"""
            
            self.results_summary.config(text=summary_text)
            
            # Store results for export
            self.last_results = results
            
            # Add details to tree
            for detail in results['details']:
                if isinstance(detail, dict):
                    rally_id = detail.get('rally_id', 'N/A')
                    action = detail.get('action', 'Unknown')
                    
                    # Handle different JIRA key field names
                    jira_key = detail.get('jira_key', detail.get('extracted_jira_key', 'N/A'))
                    
                    # Format status change based on available fields
                    if 'old_rally_status' in detail and 'new_rally_status' in detail:
                        # CAM mode fields
                        status_change = f"{detail['old_rally_status']} → {detail['new_rally_status']}"
                    elif 'old_status' in detail and 'new_status' in detail:
                        # Original mode fields
                        status_change = f"{detail['old_status']} → {detail['new_status']}"
                    elif 'rally_status' in detail:
                        status_change = detail['rally_status']
                    elif 'status' in detail:
                        status_change = detail['status']
                    else:
                        status_change = "N/A"
                    
                    message = detail.get('message', '')
                    
                    # Add JIRA summary for CAM mode if available
                    if 'jira_summary' in detail:
                        if message:
                            message = f"{message} | JIRA: {detail['jira_summary']}"
                        else:
                            message = f"JIRA: {detail['jira_summary']}"
                    
                    # Add Rally name for CAM mode if available and not too long
                    if 'rally_name' in detail and len(str(detail['rally_name'])) < 100:
                        rally_display = f"{rally_id}: {detail['rally_name']}"
                    else:
                        rally_display = rally_id
                    
                    # Add color coding based on action
                    item = self.results_tree.insert('', 'end', values=(
                        rally_display, action, jira_key, status_change, message
                    ))
                    
                    # Color code based on action
                    if action in ['status_updated', 'dry_run_update']:
                        self.results_tree.set(item, 'Action', '✅ Updated' if action == 'status_updated' else '🧪 Dry Run')
                    elif action == 'error':
                        self.results_tree.set(item, 'Action', '❌ Error')
                    elif action in ['no_jira_match', 'no_jira_references', 'jira_ticket_not_found']:
                        self.results_tree.set(item, 'Action', '🔍 No Match')
                    elif action == 'no_update_needed':
                        self.results_tree.set(item, 'Action', '✓ Same Status')
                else:
                    # Handle string messages
                    self.results_tree.insert('', 'end', values=('', 'Info', '', '', str(detail)))
            
            self.log_message(f"✅ Sync completed! Updated {results['successful_updates']} items")
            
        except Exception as e:
            self.log_message(f"❌ Error displaying results: {e}")
    
    def sync_completed(self):
        """Called when sync process completes"""
        self.sync_button.config(state='normal')
        self.stop_button.config(state='disabled')
        self.progress_var.set("Sync completed")
        self.progress_bar['value'] = 100
    
    def stop_sync_process(self):
        """Stop the sync process"""
        self.stop_sync = True
        self.progress_var.set("Stopping sync...")
        self.log_message("⛔ User requested sync stop")
    
    def manage_checkpoints(self):
        """Show checkpoint management dialog"""
        try:
            # Create checkpoint manager
            checkpoint_manager = SyncCheckpointManager()
            checkpoints = checkpoint_manager.list_active_checkpoints()
            
            # Create dialog window
            dialog = tk.Toplevel(self.root)
            dialog.title("🔄 Checkpoint Management")
            dialog.geometry("600x400")
            dialog.transient(self.root)
            dialog.grab_set()
            
            # Header
            header_frame = tk.Frame(dialog)
            header_frame.pack(fill='x', padx=10, pady=10)
            
            tk.Label(header_frame, text="🔄 Active Sync Checkpoints", 
                    font=("Arial", 16, "bold")).pack()
            tk.Label(header_frame, text="Manage interrupted sync sessions that can be resumed",
                    font=("Arial", 10), fg="gray").pack()
            
            # Checkpoints list
            if checkpoints:
                list_frame = tk.Frame(dialog)
                list_frame.pack(fill='both', expand=True, padx=10, pady=(0, 10))
                
                # Create treeview for checkpoints
                columns = ('Last Updated', 'Progress', 'Items')
                tree = ttk.Treeview(list_frame, columns=columns, show='tree headings', height=8)
                
                tree.heading('#0', text='Checkpoint File')
                tree.heading('Last Updated', text='Last Updated')
                tree.heading('Progress', text='Progress')
                tree.heading('Items', text='Items Processed')
                
                tree.column('#0', width=200)
                tree.column('Last Updated', width=150)
                tree.column('Progress', width=100)
                tree.column('Items', width=120)
                
                # Scrollbar for treeview
                scrollbar = ttk.Scrollbar(list_frame, orient='vertical', command=tree.yview)
                tree.configure(yscrollcommand=scrollbar.set)
                
                tree.pack(side='left', fill='both', expand=True)
                scrollbar.pack(side='right', fill='y')
                
                # Populate checkpoints
                for checkpoint in checkpoints:
                    try:
                        last_updated = checkpoint['last_updated']
                        if last_updated:
                            # Parse and format the timestamp
                            dt = datetime.fromisoformat(last_updated.replace('Z', '+00:00'))
                            formatted_time = dt.strftime('%Y-%m-%d %H:%M:%S')
                        else:
                            formatted_time = 'Unknown'
                        
                        progress = f"{checkpoint['processed_count']}/{checkpoint['total_items']}"
                        percentage = (checkpoint['processed_count'] / checkpoint['total_items'] * 100) if checkpoint['total_items'] > 0 else 0
                        progress_display = f"{progress} ({percentage:.1f}%)"
                        
                        tree.insert('', 'end', text=checkpoint['file'], 
                                   values=(formatted_time, progress_display, checkpoint['processed_count']))
                    except Exception as e:
                        tree.insert('', 'end', text=checkpoint['file'], 
                                   values=('Error', 'Error', 'Error'))
                
                # Buttons for checkpoint actions
                action_frame = tk.Frame(dialog)
                action_frame.pack(fill='x', padx=10, pady=10)
                
                def delete_selected():
                    selected = tree.selection()
                    if not selected:
                        messagebox.showwarning("No Selection", "Please select a checkpoint to delete.")
                        return
                    
                    if messagebox.askyesno("Delete Checkpoint", 
                                         "Are you sure you want to delete the selected checkpoint?\nThis action cannot be undone."):
                        for item in selected:
                            filename = tree.item(item, 'text')
                            try:
                                checkpoint_path = os.path.join(checkpoint_manager.checkpoint_dir, filename)
                                if os.path.exists(checkpoint_path):
                                    os.remove(checkpoint_path)
                                    tree.delete(item)
                                    messagebox.showinfo("Success", f"Deleted checkpoint: {filename}")
                            except Exception as e:
                                messagebox.showerror("Error", f"Failed to delete {filename}: {str(e)}")
                
                def delete_all():
                    if not checkpoints:
                        return
                    
                    if messagebox.askyesno("Delete All Checkpoints", 
                                         f"Are you sure you want to delete all {len(checkpoints)} checkpoints?\nThis action cannot be undone."):
                        try:
                            for checkpoint in checkpoints:
                                checkpoint_path = os.path.join(checkpoint_manager.checkpoint_dir, checkpoint['file'])
                                if os.path.exists(checkpoint_path):
                                    os.remove(checkpoint_path)
                            tree.delete(*tree.get_children())
                            messagebox.showinfo("Success", f"Deleted all {len(checkpoints)} checkpoints")
                        except Exception as e:
                            messagebox.showerror("Error", f"Failed to delete some checkpoints: {str(e)}")
                
                tk.Button(action_frame, text="🗑️ Delete Selected", command=delete_selected,
                         bg="#E74C3C", fg="white", font=("Arial", 10, "bold")).pack(side='left', padx=(0, 10))
                
                tk.Button(action_frame, text="🗑️ Delete All", command=delete_all,
                         bg="#C0392B", fg="white", font=("Arial", 10, "bold")).pack(side='left')
                
            else:
                # No checkpoints found
                empty_frame = tk.Frame(dialog)
                empty_frame.pack(fill='both', expand=True, padx=10, pady=10)
                
                tk.Label(empty_frame, text="✅ No active checkpoints found", 
                        font=("Arial", 14), fg="green").pack(pady=(50, 10))
                tk.Label(empty_frame, text="All previous sync sessions completed successfully.", 
                        font=("Arial", 11)).pack()
                tk.Label(empty_frame, text="Checkpoints are automatically created when sync is interrupted\nand cleaned up when sync completes.", 
                        font=("Arial", 10), fg="gray").pack(pady=(20, 0))
            
            # Close button
            close_frame = tk.Frame(dialog)
            close_frame.pack(fill='x', padx=10, pady=(0, 10))
            
            tk.Button(close_frame, text="Close", command=dialog.destroy,
                     bg="#7F8C8D", fg="white", font=("Arial", 11, "bold")).pack(side='right')
            
            # Center the dialog
            dialog.update_idletasks()
            x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
            y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
            dialog.geometry(f"+{x}+{y}")
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to open checkpoint management: {str(e)}")
    
    def export_results(self):
        """Export results to file"""
        if not hasattr(self, 'last_results'):
            messagebox.showwarning("No Results", "No results to export. Run a sync first.")
            return
        
        filename = filedialog.asksaveasfilename(
            title="Export Results",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
            initialvalue=f"rally_sync_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    json.dump(self.last_results, f, indent=2, default=str)
                self.log_message(f"✅ Exported results to {filename}")
                messagebox.showinfo("Success", f"Results exported to {filename}")
            except Exception as e:
                error_msg = f"Error exporting results: {e}"
                self.log_message(f"❌ {error_msg}")
                messagebox.showerror("Export Error", error_msg)
    
    def log_message(self, message: str):
        """Add message to log"""
        timestamp = datetime.now().strftime("[%H:%M:%S]")
        full_message = f"{timestamp} {message}\n"
        self.log_text.insert(tk.END, full_message)
        self.log_text.see(tk.END)
        self.root.update_idletasks()
    
    def clear_logs(self):
        """Clear log display"""
        self.log_text.delete('1.0', tk.END)
    
    def save_logs(self):
        """Save logs to file"""
        filename = filedialog.asksaveasfilename(
            title="Save Logs",
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("All files", "*.*")],
            initialvalue=f"rally_sync_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        )
        
        if filename:
            try:
                with open(filename, 'w') as f:
                    f.write(self.log_text.get('1.0', tk.END))
                messagebox.showinfo("Success", f"Logs saved to {filename}")
            except Exception as e:
                messagebox.showerror("Error", f"Error saving logs: {e}")
    
    def load_configuration(self):
        """Load configuration from .env file"""
        load_dotenv('.env.jira-rally')
        
        # Load from environment variables
        self.jira_url_var.set(os.getenv('JIRA_URL', ''))
        self.jira_user_var.set(os.getenv('JIRA_USER_EMAIL', ''))
        self.jira_token_var.set(os.getenv('JIRA_API_TOKEN', ''))
        self.jira_project_var.set(os.getenv('JIRA_PROJECT', ''))
        
        self.rally_url_var.set(os.getenv('RALLY_URL', 'https://rally1.rallydev.com'))
        self.rally_api_key_var.set(os.getenv('RALLY_API_KEY', ''))
        self.rally_workspace_var.set(os.getenv('RALLY_WORKSPACE', ''))
        self.rally_project_var.set(os.getenv('RALLY_PROJECT', ''))
        
        # Load Rally username for authentication validation
        rally_username = os.getenv('RALLY_USERNAME', '')
        if rally_username:
            self.log_message(f"ℹ️ Rally Username configured: {rally_username}")
        else:
            self.log_message("⚠️ RALLY_USERNAME not set - this may cause authentication issues")
        
        if os.path.exists('jira_rally_status_mappings.json'):
            try:
                with open('jira_rally_status_mappings.json', 'r') as f:
                    self.status_mappings = json.load(f)
                self.update_mappings_display()
                self.log_message("✅ Loaded configuration from files")
            except Exception as e:
                self.log_message(f"⚠️ Error loading mappings file: {e}")
    
    def save_configuration(self):
        """Save current configuration"""
        try:
            # Save to .env file
            env_content = f"""# Jira Configuration
JIRA_URL={self.jira_url_var.get()}
JIRA_USER_EMAIL={self.jira_user_var.get()}
JIRA_API_TOKEN={self.jira_token_var.get()}
JIRA_PROJECT={self.jira_project_var.get()}

# Rally Configuration  
RALLY_URL={self.rally_url_var.get()}
RALLY_API_KEY={self.rally_api_key_var.get()}
RALLY_WORKSPACE={self.rally_workspace_var.get()}
RALLY_PROJECT={self.rally_project_var.get()}
"""
            
            with open('.env.jira-rally', 'w') as f:
                f.write(env_content)
            
            # Save mappings
            with open('jira_rally_status_mappings.json', 'w') as f:
                json.dump(self.status_mappings, f, indent=2)
            
            self.log_message("✅ Configuration saved successfully")
            messagebox.showinfo("Success", "Configuration saved successfully!")
            
        except Exception as e:
            error_msg = f"Error saving configuration: {e}"
            self.log_message(f"❌ {error_msg}")
            messagebox.showerror("Error", error_msg)
    
    def run(self):
        """Start the GUI application"""
        self.root.mainloop()

if __name__ == "__main__":
    try:
        app = RallyJiraReverseSyncGUI()
        app.run()
    except Exception as e:
        messagebox.showerror("Application Error", f"Failed to start application: {e}")