"""
Busterville Montana Family Workout Planner Slack App
=====================================================
A Slack bot to help plan weekly workout schedules across multiple fitness studios.

Studios:
- Ballard Public Pool (Seattle Parks)
- barre3 Ballard
- solidcore Ballard  
- Cycle Sanctuary Ballard
- Greenlake Running Group (Meetup)
- Solo runs

Booking Windows:
- solidcore: Opens booking on the 1st of each month
- Cycle Sanctuary: Opens 1 week out
- barre3: Opens 1 week out
"""

import os
import re
import json
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, List
import asyncio
import urllib.parse

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

import aiohttp
from aiohttp import web
from bs4 import BeautifulSoup
import pytz

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Anthropic API for conversational features
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# OpenWeatherMap API for real weather
OPENWEATHER_API_KEY = os.environ.get("OPENWEATHER_API_KEY")
SEATTLE_LAT = 47.6062
SEATTLE_LON = -122.3321

# Google Calendar OAuth config
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "https://workout-planner-production-4139.up.railway.app/oauth/callback")
GOOGLE_SCOPES = "https://www.googleapis.com/auth/calendar.events https://www.googleapis.com/auth/calendar.readonly"

# Store for user Google tokens (in production, use a database)
user_google_tokens: Dict[str, dict] = {}

# Initialize the Slack app
app = AsyncApp(
    token=os.environ.get("SLACK_BOT_TOKEN"),
    signing_secret=os.environ.get("SLACK_SIGNING_SECRET"),
)

# Timezone for Seattle
SEATTLE_TZ = pytz.timezone('America/Los_Angeles')

# Studio configurations
STUDIOS = {
    "pool": {
        "name": "Ballard Public Pool",
        "emoji": "🏊",
        "url": "https://anc.apm.activecommunities.com/seattle/calendars?onlineSiteId=0&no_scroll_top=true&defaultCalendarId=6&locationId=26&displayType=0&view=2",
        "booking_window": "varies",
        "address": "1471 NW 67th St, Seattle, WA 98117"
    },
    "barre3": {
        "name": "barre3 Ballard",
        "emoji": "🩰",
        "url": "https://barre3.com/studio-locations/ballard/schedule#schedule_class_widget",
        "booking_window": "1 week out",
        "address": "5333 Ballard Ave NW, Seattle, WA 98107"
    },
    "solidcore": {
        "name": "solidcore Ballard",
        "emoji": "💪",
        "url": "https://solidcore.co/studios/ballard",
        "schedule_url": "https://solidcore.co/auth/schedule",
        "booking_window": "Opens 1st of month",
        "address": "2425 NW Market St, Seattle, WA 98107"
    },
    "cycle": {
        "name": "Cycle Sanctuary",
        "emoji": "🚴",
        "url": "https://www.thecyclesanctuary.com/schedule",
        "booking_window": "1 week out",
        "address": "2420 NW Market St, Seattle, WA 98107"
    },
    "greenlake": {
        "name": "Greenlake Running Group",
        "emoji": "🏃",
        "url": "https://www.meetup.com/seattle-greenlake-running-group/",
        "booking_window": "RSVP anytime",
        "schedule": "Saturdays at Green Lake"
    },
    "solo_run": {
        "name": "Solo Run",
        "emoji": "👟",
        "url": None,
        "booking_window": "N/A",
        "distance": "3-5 miles"
    }
}

# Weekly workout goals
WEEKLY_GOALS = {
    "barre3": {"min": 1, "max": 1},
    "solidcore": {"min": 1, "max": 1},
    "cycle": {"min": 1, "max": 1},
    "runs": {"min": 1, "max": 2},  # Includes greenlake + solo
    "pool": {"min": 0, "max": 1},  # Roughly every other week
    "total": {"min": 5, "max": 5}
}

# Store for user preferences and scheduled workouts
user_data = {}


def get_week_dates(start_date: Optional[datetime] = None, planning_mode: bool = False) -> list:
    """Get dates for a week (Monday-Sunday).
    
    Args:
        start_date: Optional start date
        planning_mode: If True, returns the upcoming planning week (next Monday, or today if Monday)
    """
    if start_date is None:
        start_date = datetime.now(SEATTLE_TZ)
    
    if planning_mode:
        # For planning: start from next Monday, unless today is Monday
        days_until_monday = (7 - start_date.weekday()) % 7
        if days_until_monday == 0 and start_date.hour < 12:
            # It's Monday morning, use this week
            monday = start_date
        elif days_until_monday == 0:
            # It's Monday afternoon/evening, use next week
            monday = start_date + timedelta(days=7)
        else:
            monday = start_date + timedelta(days=days_until_monday)
    else:
        # For display: show current week
        monday = start_date - timedelta(days=start_date.weekday())
    
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    
    return [monday + timedelta(days=i) for i in range(7)]


def get_booking_reminder(studio_key: str) -> str:
    """Get booking reminder based on studio booking windows."""
    today = datetime.now(SEATTLE_TZ)
    
    if studio_key == "solidcore":
        # Check if we're approaching the 1st of the month
        if today.day >= 25:
            next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
            return f"📅 *Reminder:* solidcore opens {next_month.strftime('%B')} classes on {next_month.strftime('%B 1st')}!"
        elif today.day <= 3:
            return "🔥 *solidcore booking is OPEN!* Book your classes now!"
    
    elif studio_key in ["barre3", "cycle"]:
        return f"📅 {STUDIOS[studio_key]['name']} opens classes 1 week in advance"
    
    return ""


def build_home_view(user_id: str) -> dict:
    """Build the App Home view with workout planning dashboard."""
    today = datetime.now(SEATTLE_TZ)
    this_week_dates = get_week_dates()  # Current week
    next_week_dates = get_week_dates(start_date=this_week_dates[6] + timedelta(days=1))  # Next week
    
    # Get user's scheduled workouts
    user_workouts = user_data.get(user_id, {}).get("workouts", {})
    
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🏋️ Workout Planner - Busterville Montana",
                "emoji": True
            }
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Weekly Goal:* 5 workouts\n• 1 barre3 🩰  • 1 solidcore 💪  • 1 Cycle Sanctuary 🚴\n• 1-2 runs 🏃  • 1 swim 🏊 (every other week)"
            }
        },
        {"type": "divider"}
    ]
    
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    def format_workout_text(day_workout: dict) -> str:
        """Format a workout entry with class name if available."""
        if not day_workout:
            return "_No workout planned_"
        
        studio = day_workout.get("studio", "")
        time = day_workout.get("time", "")
        class_name = day_workout.get("class_name", "")
        notes = day_workout.get("notes", "")
        
        emoji = STUDIOS.get(studio, {}).get("emoji", "✨")
        studio_name = STUDIOS.get(studio, {}).get("name", studio)
        
        # Use class_name if provided, otherwise studio name
        if class_name:
            return f"{emoji} *{class_name}* at {time}"
        elif notes and any(x in notes.lower() for x in ["signature", "cardio", "express", "full body"]):
            # If notes contain a class type, show it
            return f"{emoji} *{studio_name}: {notes}* at {time}"
        else:
            return f"{emoji} {studio_name} at {time}"
    
    def add_week_section(week_dates: list, week_label: str, is_current_week: bool = False):
        """Add a week's schedule to the blocks."""
        # Week header
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*📅 {week_label}* ({week_dates[0].strftime('%b %d')} - {week_dates[6].strftime('%b %d')})"
            }
        })
        
        # Count workouts for the week
        week_workout_count = sum(
            1 for date in week_dates 
            if user_workouts.get(date.strftime("%Y-%m-%d"))
        )
        
        if week_workout_count > 0:
            goal_status = "✅" if week_workout_count >= 5 else f"({week_workout_count}/5)"
            blocks.append({
                "type": "context",
                "elements": [{"type": "mrkdwn", "text": f"Workouts planned: {week_workout_count} {goal_status}"}]
            })
        
        for i, date in enumerate(week_dates):
            day_key = date.strftime("%Y-%m-%d")
            day_workout = user_workouts.get(day_key, {})
            workout_text = format_workout_text(day_workout)
            
            # Check if this day is today
            is_today = date.date() == today.date()
            day_label = f"*{day_names[i]} ({date.strftime('%m/%d')})*"
            if is_today:
                day_label = f"*{day_names[i]} ({date.strftime('%m/%d')})* 👈 Today"
            
            # Saturday note
            saturday_note = ""
            if i == 5:  # Saturday
                saturday_note = "\n_🏃 Greenlake Running Group meets Saturdays_"
            
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"{day_label}\n{workout_text}{saturday_note}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Edit", "emoji": True},
                    "action_id": f"plan_day_{day_key}",
                    "value": day_key
                }
            })
        
        blocks.append({"type": "divider"})
    
    # Add this week
    add_week_section(this_week_dates, "This Week", is_current_week=True)
    
    # Add next week
    add_week_section(next_week_dates, "Next Week")
    
    # Add booking reminders
    reminders = []
    for studio_key in ["solidcore", "barre3", "cycle"]:
        reminder = get_booking_reminder(studio_key)
        if reminder:
            reminders.append(reminder)
    
    if reminders:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔔 Booking Reminders*\n" + "\n".join(reminders)
            }
        })
        blocks.append({"type": "divider"})
    
    # Add quick actions
    blocks.append({
        "type": "actions",
        "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "🗓️ Plan My Week", "emoji": True},
                "action_id": "plan_week",
                "style": "primary"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "☀️ Weather", "emoji": True},
                "action_id": "check_weather"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📋 Schedules", "emoji": True},
                "action_id": "view_schedules"
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "📊 Calendar", "emoji": True},
                "action_id": "view_calendar"
            }
        ]
    })
    
    return {"type": "home", "blocks": blocks}


def build_plan_day_modal(day_key: str) -> dict:
    """Build modal for planning a specific day's workout."""
    date = datetime.strptime(day_key, "%Y-%m-%d")
    day_name = date.strftime("%A, %B %d")
    
    studio_options = [
        {
            "text": {"type": "plain_text", "text": f"{info['emoji']} {info['name']}", "emoji": True},
            "value": key
        }
        for key, info in STUDIOS.items()
    ]
    
    # Common class names for quick selection
    class_name_examples = {
        "barre3": "e.g., barre3 Signature, barre3 Cardio 45, barre3 Express 30",
        "solidcore": "e.g., Signature50: Full Body, Arms & Abs, Lower Body",
        "cycle": "e.g., Power Cycle 45, HIIT Cycle, Performance 60",
        "pool": "e.g., Lap Swim, Masters Swim",
        "greenlake": "e.g., Saturday Morning Run, Tuesday Evening Run",
        "solo_run": "e.g., 3 mile easy, 5 mile tempo"
    }
    
    return {
        "type": "modal",
        "callback_id": "plan_day_submit",
        "private_metadata": day_key,
        "title": {"type": "plain_text", "text": "Plan Workout"},
        "submit": {"type": "plain_text", "text": "Save"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": f"📅 {day_name}", "emoji": True}
            },
            {
                "type": "input",
                "block_id": "studio_select",
                "element": {
                    "type": "static_select",
                    "action_id": "studio",
                    "placeholder": {"type": "plain_text", "text": "Choose workout type"},
                    "options": studio_options
                },
                "label": {"type": "plain_text", "text": "Workout Type"}
            },
            {
                "type": "input",
                "block_id": "class_name_input",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "class_name",
                    "placeholder": {"type": "plain_text", "text": "e.g., Signature50: Full Body, barre3 Cardio 45"}
                },
                "label": {"type": "plain_text", "text": "Class Name (optional)"},
                "hint": {"type": "plain_text", "text": "Add the specific class name from the studio schedule"}
            },
            {
                "type": "input",
                "block_id": "time_select",
                "element": {
                    "type": "timepicker",
                    "action_id": "time",
                    "placeholder": {"type": "plain_text", "text": "Select time"}
                },
                "label": {"type": "plain_text", "text": "Time"}
            },
            {
                "type": "input",
                "block_id": "notes_input",
                "optional": True,
                "element": {
                    "type": "plain_text_input",
                    "action_id": "notes",
                    "multiline": True,
                    "placeholder": {"type": "plain_text", "text": "Instructor, notes, etc."}
                },
                "label": {"type": "plain_text", "text": "Notes (optional)"}
            }
        ]
    }


def build_schedules_modal() -> dict:
    """Build modal showing links to all studio schedules."""
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "📋 Studio Schedules & Booking", "emoji": True}
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": "Click links below to view schedules and book classes"
                }
            ]
        },
        {"type": "divider"}
    ]
    
    for key, studio in STUDIOS.items():
        if studio.get("url"):
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{studio['emoji']} {studio['name']}*\n📍 {studio.get('address', 'See website')}\n🗓️ Booking: {studio['booking_window']}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Schedule", "emoji": True},
                    "url": studio["url"],
                    "action_id": f"open_{key}"
                }
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{studio['emoji']} {studio['name']}*\n{studio.get('distance', '')}"
                }
            })
    
    return {
        "type": "modal",
        "title": {"type": "plain_text", "text": "Studio Schedules"},
        "close": {"type": "plain_text", "text": "Close"},
        "blocks": blocks
    }


def build_plan_week_modal(show_daily_times: bool = False, preserved_unavailable: list = None) -> dict:
    """Build modal for AI-assisted week planning."""
    week_dates = get_week_dates(planning_mode=True)
    
    day_options = [
        {
            "text": {"type": "plain_text", "text": f"{date.strftime('%A (%m/%d)')}", "emoji": True},
            "value": date.strftime("%Y-%m-%d")
        }
        for date in week_dates
    ]
    
    # Build unavailable days element with preserved selection if any
    unavailable_element = {
        "type": "multi_static_select",
        "action_id": "days",
        "placeholder": {"type": "plain_text", "text": "Select days"},
        "options": day_options
    }
    if preserved_unavailable:
        unavailable_element["initial_options"] = preserved_unavailable
    
    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🗓️ Weekly Workout Planner", "emoji": True}
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Planning for week of {week_dates[0].strftime('%B %d')} - {week_dates[6].strftime('%B %d')}"
                }
            ]
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "Tell me about your availability and I'll help create a plan that hits your goals!"
            }
        },
        {"type": "divider"},
        {
            "type": "input",
            "block_id": "unavailable_days",
            "optional": True,
            "element": unavailable_element,
            "label": {"type": "plain_text", "text": "Days I CAN'T workout"}
        },
        {
            "type": "input",
            "block_id": "preferred_times",
            "dispatch_action": True,
            "element": {
                "type": "static_select",
                "action_id": "time",
                "placeholder": {"type": "plain_text", "text": "Select preference"},
                "options": [
                    {"text": {"type": "plain_text", "text": "🌅 Early morning (5-7am)"}, "value": "early"},
                    {"text": {"type": "plain_text", "text": "☀️ Morning (7-10am)"}, "value": "morning"},
                    {"text": {"type": "plain_text", "text": "🌤️ Midday (10am-2pm)"}, "value": "midday"},
                    {"text": {"type": "plain_text", "text": "🌆 Evening (5-8pm)"}, "value": "evening"},
                    {"text": {"type": "plain_text", "text": "🔄 Varies by day (I'll specify)"}, "value": "varies"}
                ],
                **({"initial_option": {"text": {"type": "plain_text", "text": "🔄 Varies by day (I'll specify)"}, "value": "varies"}} if show_daily_times else {})
            },
            "label": {"type": "plain_text", "text": "Preferred workout time"}
        }
    ]
    
    # Add daily time preferences if "varies" was selected
    if show_daily_times:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*Set time preferences for each day:*"}
        })
        
        time_options = [
            {"text": {"type": "plain_text", "text": "🌅 Early (5-7am)"}, "value": "early"},
            {"text": {"type": "plain_text", "text": "☀️ Morning (7-10am)"}, "value": "morning"},
            {"text": {"type": "plain_text", "text": "🌤️ Midday (10am-2pm)"}, "value": "midday"},
            {"text": {"type": "plain_text", "text": "🌆 Evening (5-8pm)"}, "value": "evening"},
            {"text": {"type": "plain_text", "text": "⏭️ Skip this day"}, "value": "skip"},
        ]
        
        day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        for i, date in enumerate(week_dates):
            blocks.append({
                "type": "input",
                "block_id": f"day_time_{date.strftime('%Y-%m-%d')}",
                "optional": True,
                "element": {
                    "type": "static_select",
                    "action_id": "day_pref",
                    "placeholder": {"type": "plain_text", "text": "Select time"},
                    "options": time_options
                },
                "label": {"type": "plain_text", "text": f"{day_names[i]} ({date.strftime('%m/%d')})"}
            })
    
    blocks.extend([
        {
            "type": "input",
            "block_id": "swim_week",
            "element": {
                "type": "static_select",
                "action_id": "swim",
                "options": [
                    {"text": {"type": "plain_text", "text": "Yes, include a swim this week"}, "value": "yes"},
                    {"text": {"type": "plain_text", "text": "No, skip swimming this week"}, "value": "no"}
                ]
            },
            "label": {"type": "plain_text", "text": "Swimming this week? (every other week goal)"}
        },
        {
            "type": "input",
            "block_id": "special_requests",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "requests",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "e.g., swim Monday, barre3 Tuesday evening, solidcore Wednesday morning"}
            },
            "label": {"type": "plain_text", "text": "Specific workout requests"},
            "hint": {"type": "plain_text", "text": "Tell me which workouts you want on which days and I'll build around that"}
        }
    ])
    
    return {
        "type": "modal",
        "callback_id": "plan_week_submit",
        "private_metadata": "daily_times" if show_daily_times else "",
        "title": {"type": "plain_text", "text": "Plan My Week"},
        "submit": {"type": "plain_text", "text": "Generate Plan"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks
    }


# Event handlers
@app.event("app_home_opened")
async def handle_app_home_opened(client: AsyncWebClient, event: dict, logger):
    """Handle when user opens the App Home tab."""
    user_id = event["user"]
    
    try:
        await client.views_publish(
            user_id=user_id,
            view=build_home_view(user_id)
        )
    except Exception as e:
        logger.error(f"Error publishing home tab: {e}")


@app.action("plan_week")
async def handle_plan_week(ack, body, client: AsyncWebClient):
    """Handle click on 'Plan My Week' button."""
    await ack()
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=build_plan_week_modal()
    )


@app.action("time")  # This catches the preferred_times select
async def handle_time_preference_change(ack, body, client: AsyncWebClient):
    """Handle time preference selection - show daily inputs if 'varies' selected."""
    await ack()
    
    # Check if "varies" was selected
    selected_value = body["actions"][0].get("selected_option", {}).get("value", "")
    
    if selected_value == "varies":
        # Get current form values to preserve them
        values = body["view"]["state"]["values"]
        
        # Extract unavailable days if selected
        unavailable_selected = values.get("unavailable_days", {}).get("days", {}).get("selected_options", [])
        
        # Update modal to show daily time preferences, preserving selections
        await client.views_update(
            view_id=body["view"]["id"],
            view=build_plan_week_modal(show_daily_times=True, preserved_unavailable=unavailable_selected)
        )


@app.action("day_pref")  # Handle individual day preference selections (no-op, just ack)
async def handle_day_pref_change(ack):
    """Acknowledge day preference selections."""
    await ack()


@app.action("view_schedules")
async def handle_view_schedules(ack, body, client: AsyncWebClient):
    """Handle click on 'View Schedules' button."""
    await ack()
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=build_schedules_modal()
    )


@app.action("check_weather")
async def handle_check_weather(ack, body, client: AsyncWebClient):
    """Handle click on 'Check Weather' button."""
    await ack()
    
    weather_text = await fetch_seattle_weather()
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Seattle Weather"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": weather_text}
                }
            ]
        }
    )


@app.action("view_calendar")
async def handle_view_calendar(ack, body, client: AsyncWebClient):
    """Handle click on 'My Calendar' button - show calendar status and busy times."""
    await ack()
    
    user_id = body["user"]["id"]
    
    # Check if calendar is connected
    if user_id in user_google_tokens:
        # Calendar is connected - show busy times
        busy_times = await get_busy_times(user_id)
        
        if busy_times:
            busy_text = "*📅 Your busy times this week:*\n\n"
            for event in busy_times[:10]:  # Limit to 10
                start = event["start"]
                if start:
                    try:
                        dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                        dt_local = dt.astimezone(SEATTLE_TZ)
                        busy_text += f"• {dt_local.strftime('%A %m/%d %I:%M %p')}: {event['summary']}\n"
                    except:
                        busy_text += f"• {event['summary']}\n"
        else:
            busy_text = "*📅 Your calendar looks clear this week!*\n\nNo conflicting events found."
        
        blocks = [
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "✅ *Google Calendar Connected*"}
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": busy_text}
            }
        ]
    else:
        # Calendar not connected - show connect button
        auth_url = get_google_auth_url(user_id) if GOOGLE_CLIENT_ID else None
        
        blocks = [
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "📅 *Connect Google Calendar*\n\nLink your calendar to:\n• See busy times when planning\n• Auto-add workouts to your calendar\n• Detect existing class bookings"
                }
            }
        ]
        
        if auth_url:
            blocks.append({
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔐 Connect Google Calendar", "emoji": True},
                        "url": auth_url,
                        "action_id": "open_google_auth",
                        "style": "primary"
                    }
                ]
            })
        else:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "⚠️ _Calendar integration not configured_"}
            })
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "My Calendar"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": blocks
        }
    )


# Handle dynamic plan_day actions
@app.action(re.compile(r"plan_day_\d{4}-\d{2}-\d{2}"))
async def handle_plan_day(ack, body, client: AsyncWebClient):
    """Handle click on 'Plan Day' button for any day."""
    await ack()
    
    # Extract day_key from action_id (format: plan_day_YYYY-MM-DD)
    action = body["actions"][0]
    day_key = action["action_id"].replace("plan_day_", "")
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view=build_plan_day_modal(day_key)
    )


@app.view("plan_day_submit")
async def handle_plan_day_submit(ack, body, client: AsyncWebClient, view):
    """Handle submission of the plan day modal."""
    await ack()
    
    user_id = body["user"]["id"]
    day_key = view["private_metadata"]
    values = view["state"]["values"]
    
    studio = values["studio_select"]["studio"]["selected_option"]["value"]
    time = values["time_select"]["time"]["selected_time"]
    class_name = values.get("class_name_input", {}).get("class_name", {}).get("value", "")
    notes = values.get("notes_input", {}).get("notes", {}).get("value", "")
    
    # Save to user data
    if user_id not in user_data:
        user_data[user_id] = {"workouts": {}}
    
    user_data[user_id]["workouts"][day_key] = {
        "studio": studio,
        "time": time,
        "class_name": class_name,
        "notes": notes
    }
    
    # Update home view
    await client.views_publish(
        user_id=user_id,
        view=build_home_view(user_id)
    )


@app.view("plan_week_submit")
async def handle_plan_week_submit(ack, body, client: AsyncWebClient, view):
    """Handle submission of the plan week modal."""
    await ack()
    
    user_id = body["user"]["id"]
    values = view["state"]["values"]
    has_daily_times = view.get("private_metadata") == "daily_times"
    
    unavailable_days = values.get("unavailable_days", {}).get("days", {}).get("selected_options", [])
    unavailable = [opt["value"] for opt in unavailable_days] if unavailable_days else []
    
    preferred_time = values["preferred_times"]["time"]["selected_option"]["value"]
    include_swim = values["swim_week"]["swim"]["selected_option"]["value"] == "yes"
    special_requests = values.get("special_requests", {}).get("requests", {}).get("value", "")
    
    # Extract daily time preferences if present
    daily_prefs = {}
    if has_daily_times:
        for block_id, block_data in values.items():
            if block_id.startswith("day_time_"):
                day_key = block_id.replace("day_time_", "")
                selected = block_data.get("day_pref", {}).get("selected_option")
                if selected:
                    daily_prefs[day_key] = selected["value"]
    
    # If there are special requests, use Claude to generate the plan
    if special_requests and ANTHROPIC_API_KEY:
        suggested_plan = await generate_plan_with_claude(
            special_requests=special_requests,
            unavailable=unavailable,
            preferred_time=preferred_time,
            include_swim=include_swim,
            daily_prefs=daily_prefs
        )
    else:
        # Use the basic plan generator
        suggested_plan = generate_week_plan(unavailable, preferred_time, include_swim, daily_prefs if daily_prefs else None)
    
    # Send plan as DM
    plan_message = format_plan_message(suggested_plan)
    
    # Count workouts for summary
    workout_count = len(suggested_plan)
    
    await client.chat_postMessage(
        channel=user_id,
        text="Here's your suggested workout plan! 🏋️",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🗓️ Your Suggested Week", "emoji": True}
            },
            {
                "type": "context",
                "elements": [
                    {"type": "mrkdwn", "text": f"*{workout_count} workouts planned* — Weekly goal: 5"}
                ]
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": plan_message}
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "✅ Apply This Plan", "emoji": True},
                        "action_id": "apply_plan",
                        "style": "primary",
                        "value": json.dumps(suggested_plan)
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔄 Regenerate", "emoji": True},
                        "action_id": "plan_week"
                    }
                ]
            }
        ]
    )


@app.action("apply_plan")
async def handle_apply_plan(ack, body, client: AsyncWebClient, action):
    """Apply the suggested plan to the user's schedule."""
    await ack()
    
    user_id = body["user"]["id"]
    plan = json.loads(action["value"])
    
    if user_id not in user_data:
        user_data[user_id] = {"workouts": {}}
    
    for day_key, workout in plan.items():
        if workout:
            user_data[user_id]["workouts"][day_key] = workout
    
    # Update home view
    await client.views_publish(
        user_id=user_id,
        view=build_home_view(user_id)
    )
    
    # Check if calendar is connected and offer sync
    if user_id in user_google_tokens:
        await client.chat_postMessage(
            channel=user_id,
            text="✅ Plan applied! Check your App Home to see your schedule.",
            blocks=[
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": "✅ *Plan applied!* Check your App Home to see your schedule."}
                },
                {
                    "type": "actions",
                    "elements": [
                        {
                            "type": "button",
                            "text": {"type": "plain_text", "text": "📅 Sync to Google Calendar", "emoji": True},
                            "action_id": "sync_to_calendar",
                            "style": "primary",
                            "value": json.dumps(plan)
                        }
                    ]
                }
            ]
        )
    else:
        await client.chat_postMessage(
            channel=user_id,
            text="✅ Plan applied! Check your App Home to see your schedule.\n\n_Tip: Connect Google Calendar to sync your workouts!_"
        )


# Slash commands
@app.command("/workout")
async def handle_workout_command(ack, command, client: AsyncWebClient):
    """Handle /workout slash command."""
    await ack()
    
    text = command.get("text", "").strip().lower()
    user_id = command["user_id"]
    
    if text == "plan":
        await client.views_open(
            trigger_id=command["trigger_id"],
            view=build_plan_week_modal()
        )
    elif text == "schedules":
        await client.views_open(
            trigger_id=command["trigger_id"],
            view=build_schedules_modal()
        )
    elif text == "weather":
        weather = await fetch_seattle_weather()
        await client.chat_postMessage(
            channel=user_id,
            text=weather
        )
    elif text == "week":
        # Show this week's plan
        user_workouts = user_data.get(user_id, {}).get("workouts", {})
        week_dates = get_week_dates()
        
        message = "*Your Workout Schedule This Week:*\n\n"
        for date in week_dates:
            day_key = date.strftime("%Y-%m-%d")
            workout = user_workouts.get(day_key)
            day_name = date.strftime("%A, %m/%d")
            
            if workout:
                studio = workout["studio"]
                time = workout["time"]
                message += f"• *{day_name}*: {STUDIOS.get(studio, {}).get('emoji', '')} {STUDIOS.get(studio, {}).get('name', studio)} at {time}\n"
            else:
                message += f"• *{day_name}*: Rest day 😴\n"
        
        await client.chat_postMessage(channel=user_id, text=message)
    else:
        # Show help
        help_text = """
*🏋️ Workout Planner Commands*

`/workout plan` - Start planning your week
`/workout schedules` - View studio schedule links
`/workout weather` - Check Seattle weather
`/workout week` - See your current week's plan
`/workout help` - Show this help message

Or just open the App Home tab to see your dashboard!
        """
        await client.chat_postMessage(channel=user_id, text=help_text)


# Message handlers - Claude-powered conversational interface
@app.event("message")
async def handle_message(message, say, client: AsyncWebClient):
    """Handle all direct messages with Claude-powered conversation."""
    # Ignore bot messages and message subtypes (edits, etc.)
    if message.get("bot_id") or message.get("subtype"):
        return
    
    user_id = message["user"]
    text = message.get("text", "")
    channel = message.get("channel", "")
    
    # Only respond to DMs (channel starts with D) or app mentions
    if not channel.startswith("D"):
        return
    
    # Get user's current schedule
    user_workouts = user_data.get(user_id, {}).get("workouts", {})
    
    # Use Claude to understand and respond
    response = await chat_with_claude(text, user_workouts, user_id)
    
    # Check if Claude made changes to the schedule
    if response.get("schedule_updated"):
        # Update the user's workouts
        if user_id not in user_data:
            user_data[user_id] = {"workouts": {}}
        user_data[user_id]["workouts"] = response["new_schedule"]
        
        # Update home view
        await client.views_publish(
            user_id=user_id,
            view=build_home_view(user_id)
        )
    
    await say(response["message"])


async def chat_with_claude(user_message: str, current_schedule: dict, user_id: str) -> dict:
    """Use Claude to understand user intent and manage schedule."""
    
    if not ANTHROPIC_API_KEY:
        return {
            "message": "Chat feature not configured. Please add ANTHROPIC_API_KEY to enable conversational planning.",
            "schedule_updated": False
        }
    
    # Get both weeks
    today = datetime.now(SEATTLE_TZ)
    this_week_dates = get_week_dates()
    next_week_dates = get_week_dates(start_date=this_week_dates[6] + timedelta(days=1))
    all_dates = this_week_dates + next_week_dates
    
    # Format current schedule for Claude
    schedule_text = "*This Week:*\n"
    for date in this_week_dates:
        day_key = date.strftime("%Y-%m-%d")
        day_name = date.strftime("%A, %m/%d")
        workout = current_schedule.get(day_key)
        if workout:
            studio = workout["studio"]
            time = workout["time"]
            class_name = workout.get("class_name", "")
            name = STUDIOS.get(studio, {}).get("name", studio)
            if class_name:
                schedule_text += f"- {day_name} ({day_key}): {class_name} at {time}\n"
            else:
                schedule_text += f"- {day_name} ({day_key}): {name} at {time}\n"
        else:
            schedule_text += f"- {day_name} ({day_key}): Rest day\n"
    
    schedule_text += "\n*Next Week:*\n"
    for date in next_week_dates:
        day_key = date.strftime("%Y-%m-%d")
        day_name = date.strftime("%A, %m/%d")
        workout = current_schedule.get(day_key)
        if workout:
            studio = workout["studio"]
            time = workout["time"]
            class_name = workout.get("class_name", "")
            name = STUDIOS.get(studio, {}).get("name", studio)
            if class_name:
                schedule_text += f"- {day_name} ({day_key}): {class_name} at {time}\n"
            else:
                schedule_text += f"- {day_name} ({day_key}): {name} at {time}\n"
        else:
            schedule_text += f"- {day_name} ({day_key}): Rest day\n"
    
    # Studios info for Claude
    studios_info = """
Available studios and their keys:
- barre3: barre3 Ballard (classes at 6:00, 9:30, 12:00, 17:45)
- solidcore: solidcore Ballard (classes at 6:00, 7:00, 9:30, 12:00, 17:30, 18:30)
- cycle: Cycle Sanctuary (classes at 6:00, 9:00, 12:00, 17:30)
- pool: Ballard Public Pool / lap swim (5:30, 9:00, 12:00, 18:00)
- greenlake: Greenlake Running Group (Saturday mornings, 7:00 or 9:00)
- solo_run: Solo Run (any time, 3-5 miles)
"""
    
    # Build list of dates for reference
    date_reference = "Date reference for the next two weeks:\n"
    for date in all_dates:
        date_reference += f"- {date.strftime('%A')} = {date.strftime('%Y-%m-%d')}\n"
    
    system_prompt = f"""You are a helpful workout planning assistant for a family fitness planner. Today is {today.strftime("%A, %B %d, %Y")}.

The user's current workout schedule:
{schedule_text}

{studios_info}

{date_reference}

Weekly goals: 5 workouts total (1 barre3, 1 solidcore, 1 Cycle Sanctuary, 1-2 runs, optional swim every other week)

Your job:
1. Understand what the user wants to do with their schedule
2. If they want to make changes (move, add, remove, swap workouts, or plan specific workouts on specific days), output a JSON block with ALL the changes
3. Be friendly and conversational

CRITICAL INSTRUCTIONS FOR HANDLING REQUESTS:
- When the user asks for specific workouts on specific days (e.g., "swim Monday, barre Tuesday"), you MUST create entries for EACH workout mentioned
- Use the date reference above to convert day names to YYYY-MM-DD format
- If the user says "Monday" without specifying which week, assume THIS upcoming Monday (or today if today is Monday)
- If a day has already passed this week, use next week's date for that day
- Always include ALL requested changes in a single JSON block

IMPORTANT: If making schedule changes, you MUST include a JSON block in your response like this:
```json
{{"action": "update", "changes": {{"YYYY-MM-DD": {{"studio": "studio_key", "time": "HH:MM", "class_name": "optional class name", "notes": "optional"}}, "YYYY-MM-DD": {{"studio": "another_studio", "time": "HH:MM"}}}}}}
```

Examples:
- "swim Monday, barre Tuesday" with Monday=2026-03-09 and Tuesday=2026-03-10:
```json
{{"action": "update", "changes": {{"2026-03-09": {{"studio": "pool", "time": "09:00"}}, "2026-03-10": {{"studio": "barre3", "time": "09:30"}}}}}}
```

- "remove Thursday's workout" with Thursday=2026-03-12:
```json
{{"action": "update", "changes": {{"2026-03-12": null}}}}
```

Rules:
- Use null to remove a workout from a day
- Use the studio keys exactly: barre3, solidcore, cycle, pool, greenlake, solo_run
- Use 24-hour time format (e.g., "13:00" for 1 PM, "17:30" for 5:30 PM)
- If user doesn't specify a time, use a reasonable default for that studio
- Include class_name if the user specifies one (e.g., "barre3 Cardio 45")

If NOT making changes (just answering questions), don't include any JSON block.

Keep responses concise and friendly. Confirm what changes you're making."""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}]
                }
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Claude API error: {response.status} - {error_text}")
                    return {
                        "message": "Sorry, I had trouble understanding that. Try `/workout plan` to use the planning wizard.",
                        "schedule_updated": False
                    }
                
                data = await response.json()
                assistant_message = data["content"][0]["text"]
                
                # Check if there's a JSON block with schedule changes
                schedule_updated = False
                new_schedule = current_schedule.copy()
                
                json_match = re.search(r'```json\s*(\{.*?\})\s*```', assistant_message, re.DOTALL)
                if json_match:
                    try:
                        changes_data = json.loads(json_match.group(1))
                        if changes_data.get("action") == "update" and "changes" in changes_data:
                            for day_key, workout in changes_data["changes"].items():
                                if workout is None:
                                    # Remove workout
                                    new_schedule.pop(day_key, None)
                                else:
                                    # Add/update workout
                                    new_schedule[day_key] = {
                                        "studio": workout.get("studio", ""),
                                        "time": workout.get("time", "09:00"),
                                        "class_name": workout.get("class_name", ""),
                                        "notes": workout.get("notes", "")
                                    }
                            schedule_updated = True
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse schedule changes: {e}")
                
                # Clean up the message (remove JSON block from display)
                clean_message = re.sub(r'```json\s*\{.*?\}\s*```', '', assistant_message, flags=re.DOTALL).strip()
                
                # If schedule was updated, add confirmation
                if schedule_updated:
                    clean_message += "\n\n✅ _Schedule updated! Check your App Home to see the changes._"
                
                return {
                    "message": clean_message,
                    "schedule_updated": schedule_updated,
                    "new_schedule": new_schedule if schedule_updated else None
                }
                
    except Exception as e:
        logger.error(f"Error calling Claude: {e}")
        return {
            "message": "Sorry, I had trouble processing that. Try `/workout plan` to use the planning wizard.",
            "schedule_updated": False
        }


async def generate_plan_with_claude(special_requests: str, unavailable: list, preferred_time: str, include_swim: bool, daily_prefs: dict = None) -> dict:
    """Use Claude to generate a workout plan based on special requests."""
    
    week_dates = get_week_dates(planning_mode=True)
    today = datetime.now(SEATTLE_TZ)
    
    # Build date reference
    date_reference = ""
    for date in week_dates:
        date_reference += f"- {date.strftime('%A')} = {date.strftime('%Y-%m-%d')}\n"
    
    # Build unavailable days text
    unavailable_text = ", ".join(unavailable) if unavailable else "None"
    
    # Time preference text
    time_pref_map = {
        "early": "early morning (5-7am)",
        "morning": "morning (7-10am)", 
        "midday": "midday (10am-2pm)",
        "evening": "evening (5-8pm)",
        "varies": "varies by day"
    }
    time_pref_text = time_pref_map.get(preferred_time, preferred_time)
    
    studios_info = """
Available studios and their keys:
- barre3: barre3 Ballard (classes at 6:00, 9:30, 12:00, 17:45)
- solidcore: solidcore Ballard (classes at 6:00, 7:00, 9:30, 12:00, 17:30, 18:30)
- cycle: Cycle Sanctuary (classes at 6:00, 9:00, 12:00, 17:30)
- pool: Ballard Public Pool / lap swim (5:30, 9:00, 12:00, 18:00)
- greenlake: Greenlake Running Group (Saturday mornings, 7:00 or 9:00)
- solo_run: Solo Run (any time, 3-5 miles)
"""

    system_prompt = f"""You are a workout planning assistant. Generate a weekly workout plan based on the user's requests.

Today is {today.strftime("%A, %B %d, %Y")}.

Date reference for this week:
{date_reference}

{studios_info}

User preferences:
- Unavailable days: {unavailable_text}
- Preferred time: {time_pref_text}
- Include swimming: {"Yes" if include_swim else "No"}

Weekly goals: 5 workouts total (1 barre3, 1 solidcore, 1 Cycle Sanctuary, 1-2 runs, optional swim)

INSTRUCTIONS:
1. Parse the user's special requests to understand which workouts they want on which days
2. Honor their specific requests FIRST
3. Fill in remaining days to reach 5 workouts, avoiding unavailable days
4. Saturday should typically be Greenlake Running Group unless specified otherwise
5. Use appropriate times based on their time preference

You MUST respond with ONLY a JSON object (no other text) in this exact format:
{{"YYYY-MM-DD": {{"studio": "studio_key", "time": "HH:MM", "class_name": "optional"}}, "YYYY-MM-DD": {{"studio": "studio_key", "time": "HH:MM"}}}}

Use 24-hour time format. Use the exact studio keys: barre3, solidcore, cycle, pool, greenlake, solo_run
Only include days that have workouts (skip rest days)."""

    user_message = f"Create a workout plan with these specific requests: {special_requests}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-sonnet-4-20250514",
                    "max_tokens": 1024,
                    "system": system_prompt,
                    "messages": [{"role": "user", "content": user_message}]
                }
            ) as response:
                if response.status != 200:
                    logger.error(f"Claude API error: {response.status}")
                    # Fall back to basic plan
                    return generate_week_plan(unavailable, preferred_time, include_swim, daily_prefs)
                
                data = await response.json()
                response_text = data["content"][0]["text"].strip()
                
                # Try to parse the JSON response
                # Remove any markdown code blocks if present
                response_text = re.sub(r'```json\s*', '', response_text)
                response_text = re.sub(r'```\s*', '', response_text)
                
                try:
                    plan_data = json.loads(response_text)
                    
                    # Convert to the expected format
                    plan = {}
                    for day_key, workout in plan_data.items():
                        if workout:
                            plan[day_key] = {
                                "studio": workout.get("studio", ""),
                                "time": workout.get("time", "09:00"),
                                "class_name": workout.get("class_name", ""),
                                "notes": workout.get("notes", "")
                            }
                    
                    return plan
                    
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse Claude plan response: {e}")
                    # Fall back to basic plan
                    return generate_week_plan(unavailable, preferred_time, include_swim, daily_prefs)
                    
    except Exception as e:
        logger.error(f"Error generating plan with Claude: {e}")
        # Fall back to basic plan
        return generate_week_plan(unavailable, preferred_time, include_swim, daily_prefs)


# Helper functions
def generate_week_plan(unavailable: list, preferred_time: str, include_swim: bool, daily_prefs: dict = None) -> dict:
    """Generate a suggested workout plan based on preferences."""
    week_dates = get_week_dates(planning_mode=True)
    plan = {}
    
    # Actual class times for each studio by time preference
    # Updated to match real schedules
    studio_times = {
        "barre3": {
            "early": "06:00",
            "morning": "09:30",  # Classes at 9:30, 10:45
            "midday": "12:00",
            "evening": "17:45",  # Classes at 5:45pm, 7pm
        },
        "solidcore": {
            "early": "06:00",  # 6am, 7am classes
            "morning": "09:30",
            "midday": "12:00",
            "evening": "17:30",  # 5:30pm, 6:30pm classes
        },
        "cycle": {
            "early": "06:00",
            "morning": "09:00",
            "midday": "12:00",
            "evening": "17:30",
        },
        "pool": {
            "early": "05:30",
            "morning": "09:00",
            "midday": "12:00",
            "evening": "18:00",
        },
        "greenlake": {
            "early": "07:00",
            "morning": "09:00",
            "midday": "09:00",
            "evening": "09:00",  # Saturday runs are morning
        },
        "solo_run": {
            "early": "06:00",
            "morning": "08:00",
            "midday": "12:00",
            "evening": "18:00",
        }
    }
    
    def get_studio_time(studio: str, time_pref: str) -> str:
        """Get the appropriate class time for a studio and time preference."""
        return studio_times.get(studio, {}).get(time_pref, "09:00")
    
    # Get available days
    available_days = []
    saturday_key = None
    
    for date in week_dates:
        day_key = date.strftime("%Y-%m-%d")
        
        # Check if day is unavailable (either from unavailable list or daily_prefs marked as skip)
        if day_key in unavailable:
            continue
        if daily_prefs and daily_prefs.get(day_key) == "skip":
            continue
            
        available_days.append((date, day_key))
        if date.weekday() == 5:  # Saturday
            saturday_key = day_key
    
    # Assign workouts - ensure we hit 5 total
    assigned = []
    
    # Saturday is always Greenlake Running Group
    if saturday_key:
        time_pref = daily_prefs.get(saturday_key, preferred_time) if daily_prefs else preferred_time
        plan[saturday_key] = {
            "studio": "greenlake", 
            "time": get_studio_time("greenlake", time_pref),
            "notes": "Saturday morning run with Greenlake Running Group"
        }
        assigned.append("greenlake")
        available_days = [(d, k) for d, k in available_days if k != saturday_key]
    
    # Assign one of each required studio
    required = ["barre3", "solidcore", "cycle"]
    
    for studio in required:
        if available_days:
            date, day_key = available_days.pop(0)
            time_pref = daily_prefs.get(day_key, preferred_time) if daily_prefs else preferred_time
            plan[day_key] = {
                "studio": studio, 
                "time": get_studio_time(studio, time_pref),
                "notes": ""
            }
            assigned.append(studio)
    
    # Add swim if requested
    if include_swim and available_days:
        date, day_key = available_days.pop(0)
        time_pref = daily_prefs.get(day_key, preferred_time) if daily_prefs else preferred_time
        plan[day_key] = {
            "studio": "pool", 
            "time": get_studio_time("pool", time_pref),
            "notes": ""
        }
        assigned.append("pool")
    
    # If we need more workouts to hit 5, add a solo run
    if len(assigned) < 5 and available_days:
        # Find a weekday for solo run
        for date, day_key in available_days:
            if date.weekday() < 5:  # Weekday
                time_pref = daily_prefs.get(day_key, preferred_time) if daily_prefs else preferred_time
                plan[day_key] = {
                    "studio": "solo_run", 
                    "time": get_studio_time("solo_run", time_pref),
                    "notes": "3-5 mile run"
                }
                assigned.append("solo_run")
                break
    
    return plan


def format_plan_message(plan: dict) -> str:
    """Format a plan dictionary into a readable message."""
    week_dates = get_week_dates(planning_mode=True)
    lines = []
    
    for date in week_dates:
        day_key = date.strftime("%Y-%m-%d")
        day_name = date.strftime("%A, %m/%d")
        workout = plan.get(day_key)
        
        if workout:
            studio = workout["studio"]
            time = workout["time"]
            notes = workout.get("notes", "")
            emoji = STUDIOS.get(studio, {}).get("emoji", "✨")
            name = STUDIOS.get(studio, {}).get("name", studio)
            line = f"*{day_name}*: {emoji} {name} at {time}"
            if notes:
                line += f"\n  _{notes}_"
        else:
            line = f"*{day_name}*: Rest day 😴"
        
        lines.append(line)
    
    return "\n".join(lines)


async def fetch_seattle_weather() -> str:
    """Fetch current Seattle weather from OpenWeatherMap API."""
    
    if not OPENWEATHER_API_KEY:
        return "_Weather data not configured. Add OPENWEATHER_API_KEY to enable._"
    
    try:
        async with aiohttp.ClientSession() as session:
            # Get current weather
            current_url = f"https://api.openweathermap.org/data/2.5/weather?lat={SEATTLE_LAT}&lon={SEATTLE_LON}&appid={OPENWEATHER_API_KEY}&units=imperial"
            
            async with session.get(current_url) as response:
                if response.status != 200:
                    logger.error(f"Weather API error: {response.status}")
                    return "_Unable to fetch weather data_"
                
                current = await response.json()
            
            # Get 5-day forecast
            forecast_url = f"https://api.openweathermap.org/data/2.5/forecast?lat={SEATTLE_LAT}&lon={SEATTLE_LON}&appid={OPENWEATHER_API_KEY}&units=imperial"
            
            async with session.get(forecast_url) as response:
                if response.status != 200:
                    forecast_data = None
                else:
                    forecast_data = await response.json()
        
        # Parse current weather
        temp = round(current["main"]["temp"])
        feels_like = round(current["main"]["feels_like"])
        humidity = current["main"]["humidity"]
        wind_speed = round(current["wind"]["speed"])
        description = current["weather"][0]["description"].title()
        
        # Weather emoji mapping
        def get_weather_emoji(condition: str, icon: str) -> str:
            condition = condition.lower()
            if "rain" in condition or "drizzle" in condition:
                return "🌧️"
            elif "cloud" in condition:
                if "few" in condition or "scattered" in condition:
                    return "⛅"
                return "☁️"
            elif "snow" in condition:
                return "❄️"
            elif "thunder" in condition:
                return "⛈️"
            elif "clear" in condition:
                # Check if night
                if icon.endswith("n"):
                    return "🌙"
                return "☀️"
            elif "mist" in condition or "fog" in condition:
                return "🌫️"
            return "🌤️"
        
        current_emoji = get_weather_emoji(description, current["weather"][0]["icon"])
        
        # Build message
        message = f"{current_emoji} *Seattle Weather*\n\n"
        message += f"🌡️ *{temp}°F* ({description})\n"
        message += f"🤔 Feels like {feels_like}°F\n"
        message += f"💨 Wind: {wind_speed} mph\n"
        message += f"💧 Humidity: {humidity}%\n"
        
        # Parse forecast for the week
        if forecast_data:
            message += "\n*This Week:*\n"
            
            # Group forecast by day and get midday reading
            daily_forecasts = {}
            for item in forecast_data["list"]:
                dt = datetime.fromtimestamp(item["dt"], tz=SEATTLE_TZ)
                day_key = dt.strftime("%Y-%m-%d")
                hour = dt.hour
                
                # Prefer midday forecast (around noon)
                if day_key not in daily_forecasts or abs(hour - 12) < abs(daily_forecasts[day_key]["hour"] - 12):
                    daily_forecasts[day_key] = {
                        "temp": round(item["main"]["temp"]),
                        "description": item["weather"][0]["description"],
                        "icon": item["weather"][0]["icon"],
                        "hour": hour,
                        "day_name": dt.strftime("%a")
                    }
            
            # Show next 5 days
            today = datetime.now(SEATTLE_TZ).strftime("%Y-%m-%d")
            count = 0
            for day_key in sorted(daily_forecasts.keys()):
                if day_key <= today:
                    continue
                if count >= 5:
                    break
                    
                forecast = daily_forecasts[day_key]
                emoji = get_weather_emoji(forecast["description"], forecast["icon"])
                day_name = forecast["day_name"]
                
                # Special note for Saturday (Greenlake run day)
                if day_name == "Sat":
                    if "rain" in forecast["description"].lower():
                        message += f"• {day_name}: {forecast['temp']}°F {emoji} _(Might want backup indoor workout)_\n"
                    else:
                        message += f"• {day_name}: {forecast['temp']}°F {emoji} _(Good for Greenlake run!)_\n"
                else:
                    message += f"• {day_name}: {forecast['temp']}°F {emoji}\n"
                
                count += 1
        
        # Workout suggestion based on weather
        if "rain" in description.lower():
            message += "\n_☔ Rainy today - great day for indoor workouts!_"
        elif temp < 40:
            message += "\n_🥶 Cold out there - dress in layers for outdoor runs!_"
        elif temp > 70:
            message += "\n_🌞 Nice weather! Perfect for a run at Green Lake._"
        
        return message
        
    except Exception as e:
        logger.error(f"Weather fetch error: {e}")
        return "_Unable to fetch weather data. Please try again later._"


# =============================================================================
# Google Calendar Integration
# =============================================================================

def get_google_auth_url(user_id: str) -> str:
    """Generate Google OAuth URL for a user."""
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": GOOGLE_SCOPES,
        "access_type": "offline",
        "prompt": "consent",
        "state": user_id  # Pass user_id to link OAuth to Slack user
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


async def exchange_code_for_tokens(code: str) -> dict:
    """Exchange authorization code for access/refresh tokens."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": GOOGLE_REDIRECT_URI
            }
        ) as response:
            return await response.json()


async def refresh_access_token(refresh_token: str) -> dict:
    """Refresh an expired access token."""
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": GOOGLE_CLIENT_ID,
                "client_secret": GOOGLE_CLIENT_SECRET,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token"
            }
        ) as response:
            return await response.json()


async def get_valid_token(user_id: str) -> Optional[str]:
    """Get a valid access token for a user, refreshing if necessary."""
    tokens = user_google_tokens.get(user_id)
    if not tokens:
        return None
    
    # Check if token is expired (with 5 min buffer)
    expires_at = tokens.get("expires_at", 0)
    if datetime.now().timestamp() > expires_at - 300:
        # Refresh the token
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            return None
        
        new_tokens = await refresh_access_token(refresh_token)
        if "access_token" in new_tokens:
            tokens["access_token"] = new_tokens["access_token"]
            tokens["expires_at"] = datetime.now().timestamp() + new_tokens.get("expires_in", 3600)
            user_google_tokens[user_id] = tokens
        else:
            logger.error(f"Failed to refresh token: {new_tokens}")
            return None
    
    return tokens.get("access_token")


async def get_calendar_events(user_id: str, start_date: datetime, end_date: datetime) -> List[dict]:
    """Fetch calendar events for a date range."""
    access_token = await get_valid_token(user_id)
    if not access_token:
        return []
    
    time_min = start_date.isoformat() + "Z"
    time_max = end_date.isoformat() + "Z"
    
    async with aiohttp.ClientSession() as session:
        async with session.get(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={"Authorization": f"Bearer {access_token}"},
            params={
                "timeMin": time_min,
                "timeMax": time_max,
                "singleEvents": "true",
                "orderBy": "startTime"
            }
        ) as response:
            if response.status == 200:
                data = await response.json()
                return data.get("items", [])
            else:
                logger.error(f"Calendar API error: {response.status}")
                return []


def is_workout_event(event: dict) -> bool:
    """Check if a calendar event is a workout/fitness class."""
    summary = event.get("summary", "").lower()
    description = event.get("description", "").lower()
    location = event.get("location", "").lower()
    
    # Keywords that indicate a workout
    workout_keywords = [
        "barre3", "barre 3", "solidcore", "[solidcore]",
        "cycle sanctuary", "cycling", "spin",
        "lap swim", "swimming", "pool",
        "running", "run club", "greenlake",
        "workout", "fitness", "gym", "exercise",
        "pilates", "yoga", "hiit", "strength"
    ]
    
    # Studio-specific identifiers (from booking emails/invites)
    studio_identifiers = [
        "barre3.com", "solidcore.co", "thecyclesanctuary.com",
        "mindbodyonline", "marianatek"
    ]
    
    text_to_check = f"{summary} {description} {location}"
    
    for keyword in workout_keywords + studio_identifiers:
        if keyword in text_to_check:
            return True
    
    return False


def find_existing_workout(events: List[dict], target_date: datetime, studio_key: str) -> Optional[dict]:
    """Find if there's already a workout scheduled for this date/studio."""
    target_day = target_date.strftime("%Y-%m-%d")
    studio_info = STUDIOS.get(studio_key, {})
    studio_name = studio_info.get("name", "").lower()
    
    for event in events:
        event_start = event.get("start", {}).get("dateTime", event.get("start", {}).get("date", ""))
        if target_day in event_start:
            summary = event.get("summary", "").lower()
            
            # Check if this event matches the studio
            if studio_key == "barre3" and ("barre3" in summary or "barre 3" in summary):
                return event
            elif studio_key == "solidcore" and ("solidcore" in summary or "[solidcore]" in summary):
                return event
            elif studio_key == "cycle" and ("cycle sanctuary" in summary or "cycling" in summary):
                return event
            elif studio_key == "pool" and ("swim" in summary or "pool" in summary):
                return event
            elif studio_key == "greenlake" and ("greenlake" in summary or "running" in summary):
                return event
            elif studio_key == "solo_run" and "run" in summary:
                return event
    
    return None


async def create_calendar_event(user_id: str, workout: dict, date_str: str) -> Optional[dict]:
    """Create a calendar event for a workout."""
    access_token = await get_valid_token(user_id)
    if not access_token:
        return None
    
    studio_key = workout.get("studio", "")
    studio_info = STUDIOS.get(studio_key, {})
    time_str = workout.get("time", "09:00")
    notes = workout.get("notes", "")
    
    # Parse date and time
    start_dt = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    start_dt = SEATTLE_TZ.localize(start_dt)
    
    # Default durations by studio
    durations = {
        "barre3": 60,
        "solidcore": 50,
        "cycle": 45,
        "pool": 60,
        "greenlake": 90,
        "solo_run": 45
    }
    duration = durations.get(studio_key, 60)
    end_dt = start_dt + timedelta(minutes=duration)
    
    event = {
        "summary": f"{studio_info.get('emoji', '🏋️')} {studio_info.get('name', studio_key)}",
        "location": studio_info.get("address", ""),
        "description": f"Workout planned via Workout Planner\n{notes}".strip(),
        "start": {
            "dateTime": start_dt.isoformat(),
            "timeZone": "America/Los_Angeles"
        },
        "end": {
            "dateTime": end_dt.isoformat(),
            "timeZone": "America/Los_Angeles"
        },
        "reminders": {
            "useDefault": False,
            "overrides": [
                {"method": "popup", "minutes": 60},
                {"method": "popup", "minutes": 15}
            ]
        }
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://www.googleapis.com/calendar/v3/calendars/primary/events",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json"
            },
            json=event
        ) as response:
            if response.status == 200:
                return await response.json()
            else:
                error = await response.text()
                logger.error(f"Failed to create event: {error}")
                return None


async def sync_plan_to_calendar(user_id: str, plan: dict) -> dict:
    """Sync a workout plan to Google Calendar, avoiding duplicates."""
    if user_id not in user_google_tokens:
        return {"success": False, "error": "Calendar not connected"}
    
    # Get existing events for the week
    week_dates = get_week_dates(planning_mode=True)
    start_date = week_dates[0].replace(tzinfo=None)
    end_date = (week_dates[6] + timedelta(days=1)).replace(tzinfo=None)
    
    existing_events = await get_calendar_events(user_id, start_date, end_date)
    
    created = []
    skipped = []
    
    for date_str, workout in plan.items():
        studio_key = workout.get("studio", "")
        target_date = datetime.strptime(date_str, "%Y-%m-%d")
        
        # Check if there's already a matching workout
        existing = find_existing_workout(existing_events, target_date, studio_key)
        
        if existing:
            skipped.append({
                "date": date_str,
                "studio": studio_key,
                "existing_event": existing.get("summary", "Unknown")
            })
        else:
            # Create the event
            result = await create_calendar_event(user_id, workout, date_str)
            if result:
                created.append({
                    "date": date_str,
                    "studio": studio_key,
                    "event_id": result.get("id")
                })
    
    return {
        "success": True,
        "created": created,
        "skipped": skipped
    }


async def get_busy_times(user_id: str) -> List[dict]:
    """Get busy times for the planning week."""
    if user_id not in user_google_tokens:
        return []
    
    week_dates = get_week_dates(planning_mode=True)
    start_date = week_dates[0].replace(tzinfo=None)
    end_date = (week_dates[6] + timedelta(days=1)).replace(tzinfo=None)
    
    events = await get_calendar_events(user_id, start_date, end_date)
    
    busy_times = []
    for event in events:
        if is_workout_event(event):
            continue  # Don't show workouts as "busy"
        
        start = event.get("start", {})
        end = event.get("end", {})
        
        # Skip all-day events for now
        if "date" in start and "dateTime" not in start:
            continue
        
        busy_times.append({
            "summary": event.get("summary", "Busy"),
            "start": start.get("dateTime", ""),
            "end": end.get("dateTime", "")
        })
    
    return busy_times


# =============================================================================
# OAuth Web Server Handlers
# =============================================================================

async def handle_oauth_callback(request: web.Request) -> web.Response:
    """Handle Google OAuth callback."""
    code = request.query.get("code")
    user_id = request.query.get("state")  # We passed user_id as state
    
    if not code or not user_id:
        return web.Response(text="Missing code or state parameter", status=400)
    
    # Exchange code for tokens
    tokens = await exchange_code_for_tokens(code)
    
    if "access_token" not in tokens:
        logger.error(f"OAuth error: {tokens}")
        return web.Response(text="Failed to get access token", status=400)
    
    # Store tokens for user
    user_google_tokens[user_id] = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token"),
        "expires_at": datetime.now().timestamp() + tokens.get("expires_in", 3600)
    }
    
    logger.info(f"Successfully connected Google Calendar for user {user_id}")
    
    # Return a nice success page
    html = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Calendar Connected!</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; 
                   display: flex; justify-content: center; align-items: center; 
                   height: 100vh; margin: 0; background: #f5f5f5; }
            .container { text-align: center; padding: 40px; background: white; 
                         border-radius: 12px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }
            h1 { color: #1a5f7a; }
            p { color: #666; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>✅ Calendar Connected!</h1>
            <p>Your Google Calendar is now linked to Workout Planner.</p>
            <p>You can close this window and return to Slack.</p>
        </div>
    </body>
    </html>
    """
    return web.Response(text=html, content_type="text/html")


async def handle_health_check(request: web.Request) -> web.Response:
    """Health check endpoint."""
    return web.Response(text="OK")


# =============================================================================
# Slack Action Handlers for Calendar
# =============================================================================

@app.action("connect_calendar")
async def handle_connect_calendar(ack, body, client: AsyncWebClient):
    """Handle click on 'Connect Calendar' button."""
    await ack()
    
    user_id = body["user"]["id"]
    
    if not GOOGLE_CLIENT_ID:
        await client.chat_postMessage(
            channel=user_id,
            text="❌ Google Calendar integration is not configured. Please add GOOGLE_CLIENT_ID to the environment."
        )
        return
    
    auth_url = get_google_auth_url(user_id)
    
    await client.chat_postMessage(
        channel=user_id,
        text="🔗 *Connect Google Calendar*\n\nClick the button below to connect your Google Calendar:",
        blocks=[
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "🔗 *Connect Google Calendar*\n\nThis will allow the Workout Planner to:\n• See your busy times when planning\n• Add workout events to your calendar\n• Detect existing workout bookings"
                }
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "🔐 Connect Google Calendar", "emoji": True},
                        "url": auth_url,
                        "action_id": "open_google_auth"
                    }
                ]
            }
        ]
    )


@app.action("open_google_auth")
async def handle_open_google_auth(ack):
    """Just acknowledge - the button opens a URL."""
    await ack()


@app.action("sync_to_calendar")
async def handle_sync_to_calendar(ack, body, client: AsyncWebClient, action):
    """Sync the current plan to Google Calendar."""
    await ack()
    
    user_id = body["user"]["id"]
    
    # Check if calendar is connected
    if user_id not in user_google_tokens:
        await client.chat_postMessage(
            channel=user_id,
            text="❌ Please connect your Google Calendar first! Use the 'Connect Calendar' button in the App Home."
        )
        return
    
    # Get the plan from the action value
    try:
        plan = json.loads(action["value"])
    except:
        plan = user_data.get(user_id, {}).get("workouts", {})
    
    if not plan:
        await client.chat_postMessage(
            channel=user_id,
            text="❌ No workout plan to sync. Create a plan first!"
        )
        return
    
    # Sync to calendar
    result = await sync_plan_to_calendar(user_id, plan)
    
    if result["success"]:
        created_count = len(result["created"])
        skipped_count = len(result["skipped"])
        
        message = f"✅ *Calendar Synced!*\n\n"
        
        if created_count > 0:
            message += f"📅 Created {created_count} event(s):\n"
            for item in result["created"]:
                date = datetime.strptime(item["date"], "%Y-%m-%d").strftime("%A %m/%d")
                studio = STUDIOS.get(item["studio"], {}).get("name", item["studio"])
                message += f"• {date}: {studio}\n"
        
        if skipped_count > 0:
            message += f"\n⏭️ Skipped {skipped_count} (already on calendar):\n"
            for item in result["skipped"]:
                date = datetime.strptime(item["date"], "%Y-%m-%d").strftime("%A %m/%d")
                message += f"• {date}: {item['existing_event']}\n"
        
        await client.chat_postMessage(channel=user_id, text=message)
    else:
        await client.chat_postMessage(
            channel=user_id,
            text=f"❌ Failed to sync: {result.get('error', 'Unknown error')}"
        )


# =============================================================================
# Main Entry Point
# =============================================================================

async def main():
    # Start the web server for OAuth callbacks
    web_app = web.Application()
    web_app.router.add_get("/oauth/callback", handle_oauth_callback)
    web_app.router.add_get("/health", handle_health_check)
    
    runner = web.AppRunner(web_app)
    await runner.setup()
    
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Web server started on port {port}")
    
    # Start the Slack Socket Mode handler
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())