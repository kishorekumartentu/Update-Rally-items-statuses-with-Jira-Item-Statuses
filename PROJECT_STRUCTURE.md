# Rally-Jira Reverse Sync Project

## 📁 Clean Project Structure

This project has been cleaned up to focus solely on **Rally to Jira reverse synchronization** functionality.

### 📋 Current Files

```
rally-jira-reverse-sync/
├── .env.jira-rally                      # Configuration file (Jira & Rally settings)
├── rally_jira_reverse_sync_gui.py       # Main GUI application 
├── rally_jira_reverse_sync.bat          # Windows batch launcher
├── RALLY_JIRA_REVERSE_SYNC_README.md    # Detailed documentation
├── jira_rally_status_mappings.json      # Status mapping configuration
├── requirements.txt                     # Python dependencies
├── logs/                                # Application logs directory
├── venv/                                # Python virtual environment
└── __pycache__/                         # Python compiled files
```

### ✅ Improvements Made

1. **🎯 Added Missing Jira Project Field**
   - The GUI now includes a "Project Key" field for Jira
   - Configuration loading/saving handles JIRA_PROJECT properly
   - All sync operations use the project key for better filtering

2. **🧹 Removed Unnecessary Files**
   - Deleted all forward sync files (Jira → Rally)
   - Removed version directories (0.19.0, 1.5.1, etc.)
   - Cleaned up test files and documentation for forward sync
   - Removed unused setup scripts

3. **⚙️ Fixed Configuration**
   - Consistent field naming between GUI and .env file
   - Proper JIRA_PROJECT field integration
   - Updated load/save functionality

### 🚀 Quick Start

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Configure Settings**
   - Edit `.env.jira-rally` with your credentials
   - Set JIRA_PROJECT to your Jira project key

3. **Run Application**
   ```bash
   # Windows
   rally_jira_reverse_sync.bat
   
   # Or directly
   python rally_jira_reverse_sync_gui.py
   ```

### 🔧 Key Features

- **Reverse Sync**: Updates Rally status based on Jira issues
- **Automatic Discovery**: Finds Rally-Jira connections via FormattedIDs
- **Dry Run Mode**: Preview changes before applying
- **Status Mapping**: Configurable Jira → Rally status translations
- **Real-time Logs**: Track progress and troubleshoot issues

### 📝 Configuration Fields

**Jira Configuration:**
- URL: Your Jira instance URL
- User Email: Your Jira login email
- API Token: Jira API token for authentication
- **Project Key: Jira project key (e.g., "PROJ")**

**Rally Configuration:**
- URL: Rally server URL (defaults to https://rally1.rallydev.com)
- API Key: Rally API key
- Workspace: Rally workspace ID or name
- Project: Rally project name

This clean structure focuses on the reverse sync functionality you need while eliminating unnecessary complexity.