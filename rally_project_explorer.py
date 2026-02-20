#!/usr/bin/env python3
"""
Quick Rally project explorer to see what's actually in project 827121203631
"""

import requests
import base64
import json
from dotenv import load_dotenv
import os

def main():
    # Load environment variables
    load_dotenv('.env.jira-rally')
    
    rally_url = os.getenv('RALLY_URL')
    rally_api_key = os.getenv('RALLY_API_KEY')
    rally_workspace = os.getenv('RALLY_WORKSPACE')
    rally_project = os.getenv('RALLY_PROJECT')
    
    print(f"🔍 Checking Rally project: {rally_project}")
    print(f"🏢 Workspace: {rally_workspace}")
    print(f"🌐 URL: {rally_url}")
    
    # Prepare auth headers
    api_key_with_colon = rally_api_key + ':'
    encoded_key = base64.b64encode(api_key_with_colon.encode()).decode()
    headers = {
        'Authorization': f'Basic {encoded_key}',
        'Content-Type': 'application/json'
    }
    
    # First, let's check what artifact types exist in this project
    artifact_types = [
        'artifact',  # This gets ALL types
        'defect',
        'hierarchicalrequirement',  # User Stories
        'task',
        'testcase',
        'userstory',
        'story'
    ]
    
    base_url = f"{rally_url}/slm/webservice/v2.0"
    
    for artifact_type in artifact_types:
        try:
            print(f"\n🔍 Checking {artifact_type}...")
            
            # Build the query
            params = {
                'query': f'(Project.ObjectID = {rally_project})',
                'fetch': 'FormattedID,Name,State,ScheduleState,ObjectID,_type',
                'pagesize': 10,  # Just get first 10
                'workspace': f'/workspace/{rally_workspace}'
            }
            
            url = f"{base_url}/{artifact_type}"
            
            response = requests.get(url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                results = data.get('QueryResult', {}).get('Results', [])
                total = data.get('QueryResult', {}).get('TotalResultCount', 0)
                
                print(f"  ✅ {artifact_type}: Found {total} items")
                
                if results:
                    print(f"  📋 Sample items:")
                    for item in results[:3]:  # Show first 3
                        f_id = item.get('FormattedID', 'No ID')
                        name = item.get('Name', 'No Name')[:50] + ('...' if len(item.get('Name', '')) > 50 else '')
                        item_type = item.get('_type', 'Unknown')
                        state = item.get('State') or item.get('ScheduleState') or 'No State'
                        print(f"    - {f_id}: {name} [{item_type}] - {state}")
                else:
                    print(f"  📪 No {artifact_type} items in this project")
            else:
                print(f"  ❌ Error querying {artifact_type}: {response.status_code}")
                if response.status_code == 404:
                    print(f"    (This artifact type might not exist in Rally)")
                    
        except Exception as e:
            print(f"  ⚠️  Error with {artifact_type}: {e}")
    
    print(f"\n🔍 Summary: Checked project {rally_project} in workspace {rally_workspace}")

if __name__ == "__main__":
    main()