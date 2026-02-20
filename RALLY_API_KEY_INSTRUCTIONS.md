## Rally API Key Generation Instructions

### Step 1: Access Rally Settings
1. Go to Rally: https://rally1.rallydev.com
2. Log in with your credentials
3. Click on your profile/avatar in the top-right corner
4. Select "Settings" from the dropdown menu

### Step 2: Generate New API Key
1. In Settings, click on "API Keys" tab
2. Click "Create New API Key" button
3. Give it a descriptive name (e.g., "Jira Sync Tool - [Current Date]")
4. **IMPORTANT**: Make sure you're logged in with your correct Rally username
5. Copy the generated API key immediately (you won't see it again)

### Step 3: Check Your Account Status
- Verify your account is active
- Check if your organization uses Broadcom SSO/SAML
- Ensure you have proper permissions to access the workspace/project

### Step 4: Alternative if Rally redirects to Broadcom
If Rally redirects you to Broadcom login:
1. Go to: https://access.broadcom.com
2. Log in with your Broadcom credentials  
3. Navigate to Rally from there
4. Generate API key from the Broadcom-integrated Rally interface

### Step 5: Update Environment File
Update the following values in your .env.jira-rally file:
- Replace RALLY_API_KEY with your generated API key
- Replace RALLY_USERNAME with your Rally username (usually your email prefix)
- Replace RALLY_URL, RALLY_WORKSPACE, and RALLY_PROJECT with your specific values

### Required Information to Gather:
- **Rally API Key**: Generated from Step 2
- **Rally Username**: Your Rally login username
- **Rally Workspace ID**: Numeric ID of your Rally workspace
- **Rally Project ID**: Numeric ID or name of your Rally project
- **Jira URL**: Your Jira instance URL (e.g., https://yourcompany.atlassian.net)
- **Jira API Token**: Generated from Jira Account Settings → Security → API tokens
- **Jira Project Key**: Your Jira project identifier

### Troubleshooting Tips:
- API keys expire after a certain period (usually 1 year)
- The username that creates the API key must match the username in your config
- Some organizations require special permissions for API access
- Broadcom acquisition may have changed authentication requirements