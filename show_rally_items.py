#!/usr/bin/env python3
"""
Show actual Rally items in your project for testing filters
"""

import requests
import base64
from dotenv import load_dotenv
import os

def show_actual_rally_items():
    """Show what Rally items actually exist in your project"""
    
    load_dotenv('.env.jira-rally')
    
    rally_url = os.getenv('RALLY_URL')
    rally_api_key = os.getenv('RALLY_API_KEY')
    rally_workspace = os.getenv('RALLY_WORKSPACE')
    rally_project = os.getenv('RALLY_PROJECT')
    
    print(f"📋 Showing actual Rally items in project: {rally_project}")
    
    # Prepare auth headers
    api_key_with_colon = rally_api_key + ':'
    encoded_key = base64.b64encode(api_key_with_colon.encode()).decode()
    headers = {'Authorization': f'Basic {encoded_key}', 'Content-Type': 'application/json'}
    
    base_url = f"{rally_url}/slm/webservice/v2.0"
    
    # Get sample items from each type
    for item_type, type_name in [('defect', 'Defects'), ('hierarchicalrequirement', 'User Stories'), ('task', 'Tasks')]:
        print(f"\n🔍 {type_name} in your project:")
        
        try:
            params = {
                'query': f'(Project.ObjectID = {rally_project})',
                'fetch': 'FormattedID,Name,State,ScheduleState',
                'pagesize': 10,  # Get first 10 items
                'workspace': f'/workspace/{rally_workspace}'
            }
            
            response = requests.get(f"{base_url}/{item_type}", headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('QueryResult', {}).get('Results', [])
                total = data.get('QueryResult', {}).get('TotalResultCount', 0)
                
                print(f"   📊 Total {type_name}: {total}")
                
                if results:
                    print(f"   📋 Sample items (showing first {len(results)}):")
                    for item in results:
                        f_id = item.get('FormattedID')
                        name = item.get('Name', '')[:60]
                        state = item.get('State') or item.get('ScheduleState') or 'No State'
                        
                        # Check if it contains JIRA references
                        has_jira = '✅' if ('CAM-' in name or 'JIRA|' in name) else '⚪'
                        
                        print(f"     {has_jira} {f_id}: {name} [{state}]")
                        
                        # Show filter syntax examples
                        if f_id:
                            print(f"       Filter syntax: (FormattedID = \"{f_id}\")")
                            break  # Just show one example
                else:
                    print(f"   📪 No {type_name} found")
                    
        except Exception as e:
            print(f"   ❌ Error checking {type_name}: {e}")

if __name__ == "__main__":
    show_actual_rally_items()