# 🔄 Checkpoint & Resume Functionality

## Overview

The Rally-Jira synchronization tool now includes **automatic checkpoint/resume functionality** to handle network interruptions and large sync operations gracefully. When a sync is interrupted, you can resume from where it left off instead of starting from scratch.

## ✨ Key Features

### Automatic Checkpoint Creation
- **Periodic Saving**: Progress is automatically saved every 5% of processed items
- **Error Recovery**: Checkpoint is saved when sync encounters errors 
- **Smart Resume**: Detects and skips already processed items when resuming

### User-Friendly Resume Dialog
- **Automatic Detection**: Tool detects if there's an incomplete sync from before
- **Progress Information**: Shows how many items were already processed
- **User Choice**: Option to resume from checkpoint or start fresh

### Checkpoint Management
- **Management Dialog**: New "🔄 Checkpoints" button to view and manage saved checkpoints
- **Auto Cleanup**: Successful sync completion automatically removes checkpoints
- **Manual Control**: Ability to delete specific or all checkpoints

## 🚀 How to Use

### Normal Operation
1. **Start Sync**: Click "🚀 Start Sync" as usual
2. **Interruption Handling**: If network issues or errors occur, progress is automatically saved
3. **Resume**: Next time you click "Start Sync", you'll be asked if you want to resume

### Resume Dialog Options
When resuming is available, you'll see a dialog with three options:

- **YES (Resume)**: Continue from where it stopped, skipping already processed items
- **NO (Start Fresh)**: Clear checkpoint and start over from the beginning  
- **CANCEL**: Exit without starting sync

### Checkpoint Management
Click the **"🔄 Checkpoints"** button to:
- View all active checkpoints with timestamps and progress
- Delete specific checkpoints you no longer need
- Clear all checkpoints if desired

## 📋 Technical Details

### Checkpoint Data Structure
```json
{
  "processed_items": ["US12345", "DE67890", "TA11111"],
  "total_items": 500,
  "start_time": "2024-02-18T10:30:00",
  "last_updated": "2024-02-18T10:45:00", 
  "current_progress": {
    "items_processed": 150,
    "results_summary": {
      "jira_tickets_found": 120,
      "successful_updates": 95,
      "errors": 5
    }
  },
  "sync_config": {
    "item_types": ["HierarchicalRequirement", "Defect"],
    "rally_filter": "",
    "rally_project": "12345",
    "sync_mode": "cam_references"
  }
}
```

### Checkpoint File Storage
- **Location**: `sync_checkpoints/` folder in your workspace directory
- **Naming**: `sync_checkpoint_<config_hash>.json` (unique per configuration)
- **Automatic**: Created/updated/deleted automatically during sync operations

### Resume Logic
1. **Configuration Matching**: Checkpoints are tied to specific sync configurations (item types, filters, projects)
2. **Item Filtering**: Already processed Rally items are skipped during resume
3. **Progress Calculation**: Progress bar accounts for both completed and remaining items
4. **Status Preservation**: All results and statistics are preserved across resume sessions

## 🎯 Supported Sync Modes

### ✅ CAM References Mode (Full Support)
- **Checkpoint saving**: Every 5% of items processed
- **Resume capability**: Full resume from any point
- **Progress tracking**: Detailed progress information
- **Auto cleanup**: Checkpoints removed on successful completion

### ⚠️ Rally ID Search Mode (No Checkpoint Support)
- Uses original sync function without checkpoint capability
- Recommended to switch to CAM References mode for large sync operations

## 🔍 Benefits

### Network Resilience
- **No Lost Progress**: Hours of sync work won't be lost due to temporary network issues
- **Efficient Recovery**: Resume exactly where interruption occurred
- **Bandwidth Saving**: No need to re-fetch and re-process completed items

### Large Dataset Handling
- **Scalable**: Handle thousands of Rally items without fear of starting over
- **Memory Efficient**: Only load items that still need processing
- **Time Saving**: Potentially save hours on large synchronization jobs

### User Experience
- **Transparent**: Minimal impact on normal workflow
- **Informative**: Clear progress and resume information
- **Flexible**: Choice to resume or start fresh based on situation

## 🛠️ Troubleshooting

### Checkpoint Issues
- **Corrupted Checkpoint**: Use "🔄 Checkpoints" button to delete problematic files
- **Old Checkpoints**: Checkpoints older than 24 hours are still usable but flagged
- **Permission Issues**: Ensure write access to workspace directory

### Resume Problems
- **Configuration Changes**: New filters/selections create fresh sync (old checkpoint won't match)
- **Project Changes**: Different Rally/Jira projects require fresh sync
- **Manual Reset**: Use checkpoint management dialog to clear and restart

## 📝 Example Workflow

```
1. Start sync with 1000 Rally items
2. ⚠️ Network error occurs after processing 400 items
3. Restart application, click "🚀 Start Sync"
4. 💬 Dialog appears: "Resume from checkpoint? 400/1000 items processed"
5. ✅ Click "Yes" to resume
6. 🔄 Sync continues from item 401, skipping first 400 items
7. ✅ Completion: Checkpoint automatically deleted
```

This enhancement makes the Rally-Jira sync tool much more robust and suitable for production use with large datasets and unreliable networks.