# 🏋️ Workout Planner - Busterville Montana Family Slack App

A Slack bot to help plan weekly workout schedules across multiple Ballard fitness studios.

## 🎯 Features

### Studios Supported
| Studio | Booking Window | Notes |
|--------|---------------|-------|
| 🏊 Ballard Public Pool | Varies | [Schedule](https://anc.apm.activecommunities.com/seattle/calendars?onlineSiteId=0&no_scroll_top=true&defaultCalendarId=6&locationId=26&displayType=0&view=2) |
| 🩰 barre3 Ballard | 1 week out | [Schedule](https://barre3.com/studio-locations/ballard/schedule#schedule_class_widget) |
| 💪 solidcore Ballard | Opens 1st of month | [Schedule](https://solidcore.co/studios/ballard) |
| 🚴 Cycle Sanctuary | 1 week out | [Schedule](https://www.thecyclesanctuary.com/schedule) |
| 🏃 Greenlake Running Group | RSVP anytime | [Meetup](https://www.meetup.com/seattle-greenlake-running-group/) |
| 👟 Solo Run | N/A | 3-5 miles |

### Weekly Goals
- **5 total workouts per week**
  - 1x barre3
  - 1x solidcore
  - 1x Cycle Sanctuary
  - 1-2x runs (Saturday Greenlake + weekday solo)
  - 1x swim (every other week)

### App Features
- 📅 **Weekly Planning Dashboard** - Plan your entire week at once
- 🗓️ **Day-by-Day Scheduling** - Assign specific workouts to specific days
- 🔔 **Booking Reminders** - Never miss a booking window
- ☀️ **Weather Integration** - Check Seattle weather for outdoor runs
- 📊 **Calendar Sync** - See your availability alongside work calendar

## 🚀 Setup Instructions

### Step 1: Create the Slack App

1. Go to [api.slack.com/apps](https://api.slack.com/apps)
2. Click **Create New App**
3. Choose **From an app manifest**
4. Select your **Busterville Montana** workspace
5. Paste the contents of `manifest.json`
6. Click **Create**

### Step 2: Get Your Tokens

1. **Bot Token**: Go to **OAuth & Permissions** → **Install to Workspace** → Copy the **Bot User OAuth Token** (starts with `xoxb-`)

2. **Signing Secret**: Go to **Basic Information** → **App Credentials** → Copy **Signing Secret**

3. **App Token**: Go to **Basic Information** → **App-Level Tokens** → **Generate Token**
   - Name it `socket-mode`
   - Add scope: `connections:write`
   - Copy the token (starts with `xapp-`)

### Step 3: Configure Environment

```bash
# Copy template
cp .env.template .env

# Edit with your tokens
nano .env
```

Fill in:
```
SLACK_BOT_TOKEN=xoxb-your-bot-token
SLACK_SIGNING_SECRET=your-signing-secret
SLACK_APP_TOKEN=xapp-your-app-token
```

### Step 4: Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
```

### Step 5: Run the App

```bash
python app.py
```

You should see:
```
⚡️ Bolt app is running!
```

## 📱 Using the App

### App Home Tab
Open the **Workout Planner** app in Slack and click the **Home** tab to see:
- Your weekly schedule
- Quick planning buttons
- Booking reminders

### Slash Commands

| Command | Description |
|---------|-------------|
| `/workout plan` | Start planning your week |
| `/workout schedules` | View all studio schedule links |
| `/workout weather` | Check Seattle weather |
| `/workout week` | See your current week's plan |
| `/workout help` | Show help message |

### Messaging
Just mention workouts in any channel and the bot will respond with relevant studio info!

## 📁 Project Structure

```
workout-planner-slack-app/
├── app.py              # Main application code
├── requirements.txt    # Python dependencies
├── manifest.json       # Slack app manifest
├── .env.template       # Environment variables template
└── README.md          # This file
```

## 🔧 Customization

### Add More Studios
Edit the `STUDIOS` dictionary in `app.py`:

```python
STUDIOS = {
    "new_studio": {
        "name": "Studio Name",
        "emoji": "🏃",
        "url": "https://...",
        "booking_window": "1 week out",
        "address": "..."
    },
    ...
}
```

### Change Weekly Goals
Edit the `WEEKLY_GOALS` dictionary:

```python
WEEKLY_GOALS = {
    "barre3": {"min": 1, "max": 1},
    "solidcore": {"min": 1, "max": 1},
    ...
}
```

## 🌐 Deployment Options

### Local Development
Run locally with Socket Mode (current setup).

### Heroku
```bash
heroku create workout-planner
heroku config:set SLACK_BOT_TOKEN=xoxb-...
heroku config:set SLACK_SIGNING_SECRET=...
heroku config:set SLACK_APP_TOKEN=xapp-...
git push heroku main
```

### Docker
```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "app.py"]
```

## 🔮 Future Enhancements

- [ ] **Google Calendar Integration** - Auto-check work calendar availability
- [ ] **Studio Schedule Scraping** - Pull real class times from studio websites
- [ ] **Real Weather API** - Live Seattle weather data
- [ ] **Recurring Schedules** - Set up standard weekly templates
- [ ] **Booking Links** - Direct links to book specific classes
- [ ] **Family Sharing** - Coordinate schedules with family members

## 🐛 Troubleshooting

### "Bolt app is not responding"
- Check that all three tokens are set correctly
- Ensure Socket Mode is enabled in Slack app settings
- Verify bot has been invited to channels

### "Permission denied"
- Re-install the app to workspace
- Check OAuth scopes match manifest

### "Home tab not updating"
- Trigger an event (close and reopen Home tab)
- Check app logs for errors

## 📞 Support

This app was built for the Busterville Montana family. For issues:
1. Check the troubleshooting section
2. Review Slack's [Bolt documentation](https://slack.dev/bolt-python/)
3. Open an issue in this repository

---

Made with ❤️ for family fitness! 🏋️‍♀️🏃‍♂️🚴‍♀️🏊‍♂️
