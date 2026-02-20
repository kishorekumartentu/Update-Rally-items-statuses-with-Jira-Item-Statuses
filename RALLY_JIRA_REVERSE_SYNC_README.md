# Rally to Jira Reverse Sync GUI

## 🎯 Overview

This GUI application performs **reverse synchronization** from Rally to Jira. Instead of requiring Rally Field IDs in Jira, it:

1. **Fetches Rally items** (User Stories, Defects, Tasks) from your Rally project
2. **Searches Jira issues** for Rally FormattedIDs (US123, DE456, etc.)
3. **Updates Rally status** to match the corresponding Jira issue status
4. **No Configuration Hassle** - No need to find custom field IDs!

## ✅ Key Benefits

- **🔍 Automatic Discovery**: Finds Rally-Jira connections automatically
- **🛡️ Safe Mode**: Dry-run option to preview changes
- **📊 Detailed Results**: Shows exactly what will be updated
- **⚙️ Configurable**: Custom status mappings and filters
- **👀 Real-time Logs**: See progress and troubleshoot issues
- **🎯 Single Issue Lookup**: Check individual JIRA issues and their Rally connections

## 🚀 Quick Start

### Prerequisites
- Python 3.7+ installed
- Jira and Rally access with appropriate permissions
- **Complete setup first**: See [SETUP.md](SETUP.md) for detailed configuration instructions

### 1. Initial Setup
Before using the application, you must configure your API keys and connection details:

1. **Read the Setup Guide**: Follow [SETUP.md](SETUP.md) for complete setup instructions
2. **Configure Environment**: Fill in your API keys and connection details in `.env.jira-rally`
3. **Test Connections**: Use the Configuration tab to verify connections work

### 2. Launch the Application
```bash
# Double-click this file:
rally_jira_reverse_sync.bat

# Or run directly:
python rally_jira_reverse_sync_gui.py
```

### 3. Configure Connections (First Time)
**Configuration Tab:**
- Enter your **Jira URL, email, and API token** (see [SETUP.md](SETUP.md) for details)
- Enter your **Rally API key, workspace, and project** (see [SETUP.md](SETUP.md) for details)
- Test connections to verify everything works

### 4. Run Sync
**Sync Operations Tab:**
- Choose Rally item types (User Stories, Defects, Tasks)
- Optionally add Rally query filters
- **Enable Dry Run** for first test
- Click "🚀 Start Sync"

### 3.5. Single JIRA Issue Lookup
**Sync Operations Tab - Single Issue Lookup:**
- Enter any JIRA issue key (e.g., "PROJ-123")
- Click "🔍 Lookup" to find related Rally items
- View current Rally status and what it would be updated to
- If no Rally items reference the JIRA issue, it will show "No items found"

### 4. Review Results
**Results Tab:**
- See summary of items processed
- Review detailed action log
- Export results if needed

## 🔧 Configuration

**⚠️ First-time users**: Please follow the complete setup guide in [SETUP.md](SETUP.md) before proceeding.

### Jira Setup
- **URL**: Your Jira instance URL (e.g., `https://yourcompany.atlassian.net`)
- **Email**: Your Jira login email
- **API Token**: Generate from Jira Account Settings → Security → API tokens

### Rally Setup
- **URL**: Your Rally instance URL (usually `https://rally1.rallydev.com`)
- **API Key**: Generate from Rally Profile → API Keys
- **Workspace**: Your Rally workspace ID (numeric)
- **Project**: Your Rally project ID (numeric) or project name

### Status Mappings
Configure how Jira statuses map to Rally statuses:
- **Default mappings included**: Common status mappings
- **Load custom mappings**: JSON file with your specific mappings
- **Example mapping**: `"In Progress" → "In-Progress"`

## � Single JIRA Issue Lookup

Need to quickly check what would happen to a specific JIRA issue? Use the **Single JIRA Issue Lookup** feature:

### How to Use
1. Go to the **Sync Operations** tab
2. Find the "🔍 Single JIRA Issue Lookup" section
3. Enter any JIRA issue key (e.g., `PROJ-123`, `TICKET-456`)
4. Click "🔍 Lookup"

### What You'll See
- **JIRA Issue Details**: Key, summary, and current status
- **Related Rally Items**: Any Rally items that reference this JIRA issue
- **Current Rally Status**: What status the Rally items currently have
- **Proposed Status**: What the Rally items would be updated to
- **Update Needed**: Whether a status change is required

### Example Output
```
✅ JIRA Issue Found:
   Key: PROJ-123
   Summary: Implement user authentication
   Status: In Progress

🎯 Related Rally Items Found (1):

   📋 HierarchicalRequirement: US456
      Name: User login functionality for PROJ-123
      Current Status: Defined
      Would Update To: In-Progress
      🔄 Status change needed
```

### If No Rally Items Found
If no Rally items reference the JIRA issue, you'll see:
```
ℹ️ No Rally items found that reference this JIRA issue.
   This JIRA issue may not be linked to any Rally work items.
```

This feature helps you:
- **Verify connections** between JIRA and Rally items
- **Preview changes** for specific issues
- **Debug** why certain items aren't syncing
- **Check status mappings** for individual cases

## �📋 How Search Works

The application searches for Rally FormattedIDs in Jira using multiple strategies:

1. **Issue Summary**: Searches issue titles for Rally IDs
2. **Description**: Searches issue descriptions
3. **Comments**: Searches issue comments

**Example matches:**
- Issue title: "US123: Implement user login"
- Description: "Related to Rally item DE456"
- Comment: "Fixing defect TA789"

## 🛡️ Safe Usage

### Dry Run Mode (Recommended First)
- **Always enable** for first sync
- Shows exactly what would be updated
- No changes made to Rally
- Review results before real sync

### Rally Query Filters
Use Rally query syntax to limit items:
```
Examples:
(State = "In-Progress")
(Iteration.Name = "Sprint 1")  
(Owner.Name = "John Doe")
(State = "Completed") AND (Iteration.Name contains "Sprint")
```

## 📊 Results Interpretation

### Action Types
- **✅ Updated**: Rally item status was updated
- **✓ Same Status**: No update needed (statuses already match)
- **🔍 No Match**: Rally item not found in Jira
- **❌ Error**: Update failed (check logs)

### Export Options
- **JSON Export**: Detailed results for analysis
- **Log Export**: Full execution logs

## 🔍 Troubleshooting

### Common Issues

**"No Rally items found"**
- Check Rally project name spelling
- Verify Rally workspace access
- Try without query filters first

**"No Jira matches found"**
- Ensure Jira issues contain Rally FormattedIDs in title/description
- Check Jira search permissions
- Try searching manually in Jira for Rally ID

**"Connection failed"**
- Verify URLs and credentials
- Check network connectivity
- Ensure API tokens are not expired

### Debugging Steps
1. **Enable Dry Run** and check results
2. **Test Connections** before syncing
3. **Check Logs tab** for detailed error messages
4. **Start with small filter** to test subset of items
5. **Export results** to analyze patterns

## 📁 Files Generated

- **`.env.rally-jira-reverse`**: Saved configuration
- **`jira_rally_status_mappings.json`**: Status mappings
- **`rally_sync_results_*.json`**: Exported results
- **`rally_sync_logs_*.txt`**: Exported logs

## 🆚 vs Original Approach

| Feature | Original (Jira→Rally) | New (Rally→Jira) |
|---------|----------------------|-------------------|
| **Setup Complexity** | High (Rally Field ID needed) | Low (automatic search) |
| **Direction** | Jira status → Rally | Rally status ← Jira |
| **Link Method** | Custom field required | Content search |
| **Maintenance** | Field ID maintenance | Zero maintenance |
| **Flexibility** | Limited to linked items | Finds all connections |

## 🔄 Sync Process Flow

```
1. Connect to Rally & Jira
2. Fetch Rally items (by type & filter)
3. For each Rally item:
   └── Search Jira for FormattedID
   └── If found: Compare statuses
   └── If different: Update Rally status
   └── Log result
4. Generate summary report
```

## ⚠️ Important Notes

- **Backup recommended** before first production sync
- **Test with dry run** in non-production environment
- **Status mappings** should be reviewed and customized
- **Permissions required**: Jira search + Rally update access
- **Rate limits**: Application handles API rate limiting automatically

## 💡 Tips for Success

1. **Start small**: Test with a few items using Rally filters
2. **Verify mappings**: Ensure status mappings make sense for your workflow
3. **Use descriptive Rally IDs**: Help search matching by including Rally IDs in Jira titles
4. **Regular syncs**: Run periodically to keep systems in sync
5. **Monitor results**: Review logs for any patterns or issues

---

**Need Help?** Check the application logs or test connections to identify specific issues.