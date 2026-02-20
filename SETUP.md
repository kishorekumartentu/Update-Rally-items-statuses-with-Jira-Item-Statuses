# Rally-Jira Reverse Sync Setup Guide

## 🚀 Quick Setup Checklist

Follow these steps to set up the Rally-Jira Reverse Sync application for your organization:

### Prerequisites
- [ ] Python 3.7+ installed
- [ ] Access to your Jira instance with API token generation permissions
- [ ] Access to your Rally instance with API key generation permissions
- [ ] Appropriate permissions to read Jira issues and update Rally items

## 📋 Step 1: Configure Environment Variables

Edit the `.env.jira-rally` file and fill in the following values:

### Jira Configuration
```env
# Replace with your Jira instance URL (e.g., https://yourcompany.atlassian.net)
JIRA_URL=

# Replace with your Jira email address
JIRA_USER_EMAIL=

# Generate from Jira Account Settings → Security → API tokens
JIRA_API_TOKEN=

# Replace with your Jira project key (e.g., PROJ, TICKET, etc.)
JIRA_PROJECT=
```

### Rally Configuration
```env
# Replace with your Rally URL (usually https://rally1.rallydev.com)
RALLY_URL=

# Generate from Rally Profile → API Keys tab
RALLY_API_KEY=

# Replace with your Rally workspace ID (numeric value)
RALLY_WORKSPACE=

# Replace with your Rally project ID (numeric) or project name
RALLY_PROJECT=

# Replace with your Rally username (usually your email prefix)
RALLY_USERNAME=
```

## 🔑 Step 2: Generate API Credentials

### Jira API Token
1. Log into your Jira instance
2. Go to **Account Settings** → **Security** → **API tokens**
3. Click **Create API token**
4. Give it a descriptive name (e.g., "Rally-Jira Sync Tool")
5. Copy the token and paste it into `JIRA_API_TOKEN` in your .env file

### Rally API Key
1. Log into your Rally instance (usually https://rally1.rallydev.com)
2. Click on your profile/avatar → **Settings**
3. Go to **API Keys** tab
4. Click **Create New API Key**
5. Give it a descriptive name (e.g., "Jira Sync Tool")
6. Copy the key and paste it into `RALLY_API_KEY` in your .env file

**Important**: The Rally username in the config must match the user who created the API key!

## 🏗️ Step 3: Find Your Rally Project Information

### Finding Rally Workspace ID
1. In Rally, go to your main workspace
2. Look at the URL - the workspace ID is typically the long number in the URL
3. Or use the Rally Project Explorer tool included with this application

### Finding Rally Project ID
1. Navigate to your project in Rally
2. The project ID can be found in the URL or project settings
3. You can use either the numeric ObjectID or the project name

## 🧪 Step 4: Install Dependencies

```bash
# Install required Python packages
pip install -r requirements.txt
```

Or if you prefer using a virtual environment:

```bash
# Create virtual environment
python -m venv venv

# Activate it (Windows)
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## ✅ Step 5: Test Your Configuration

### Launch the Application
```bash
# Method 1: Double-click the batch file
rally_jira_reverse_sync.bat

# Method 2: Run directly
python rally_jira_reverse_sync_gui.py
```

### Test Connections
1. Open the application
2. Go to the **Configuration** tab
3. Click **Test Jira Connection**
4. Click **Test Rally Connection**
5. Verify both connections are successful

## 🔧 Step 6: Configure Status Mappings

The application includes default status mappings, but you should review and customize them:

1. In the application, go to **Configuration** tab
2. Review the status mappings
3. Modify them to match your organization's workflow
4. Save the configuration

### Common Status Mappings
- Jira "In Progress" → Rally "In-Progress"
- Jira "Done" → Rally "Completed"
- Jira "To Do" → Rally "Defined"

## 🎯 Step 7: Run Your First Sync

### Recommended First Run
1. Go to **Sync Operations** tab
2. **Enable Dry Run** (this won't make actual changes)
3. Add a Rally filter to limit items (e.g., `(State = "In-Progress")`)
4. Click **Start Sync**
5. Review results in the **Results** tab

### If Everything Looks Good
1. Disable Dry Run
2. Run the sync again to make actual updates
3. Monitor the **Logs** tab for any issues

## 📊 Understanding the Results

### Status Indicators
- **✅ Updated**: Rally item status successfully changed
- **✓ Same Status**: No update needed (statuses already match)
- **🔍 No Match**: Rally item not found in any Jira issue
- **❌ Error**: Update failed (check logs for details)

## 🔍 Troubleshooting Common Issues

### Authentication Issues
- **Jira 401 Unauthorized**: Check email and API token
- **Rally 401 Unauthorized**: Check API key and username match
- **Rally 403 Forbidden**: Check workspace and project permissions

### Connection Issues
- **Network timeouts**: Check URLs and network connectivity
- **DNS resolution**: Verify Jira/Rally URLs are correct

### Data Issues
- **No Rally items found**: Check project name and filters
- **No Jira matches**: Ensure Jira issues contain Rally IDs in title/description

### Getting Help
1. Check the **Logs** tab in the application
2. Export logs for detailed analysis
3. Use the **Single Issue Lookup** feature to debug specific items
4. Review the Rally query syntax if using filters

## 📁 Important Files

- **`.env.jira-rally`**: Your configuration (keep private!)
- **`jira_rally_status_mappings.json`**: Status mappings
- **`requirements.txt`**: Python dependencies
- **`logs/`**: Application logs directory
- **`sync_checkpoints/`**: Sync checkpoint data

## 🔒 Security Notes

- **Never commit** `.env.jira-rally` to version control
- **Protect your API keys** - treat them like passwords
- **Regularly rotate** API keys for security
- **Use least privilege** - ensure accounts only have necessary permissions

---

**Ready to sync?** Once setup is complete, you can run regular syncs to keep Rally and Jira in sync!