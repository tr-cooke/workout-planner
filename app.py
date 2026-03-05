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
from typing import Optional
import asyncio

from slack_bolt.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

import aiohttp
from bs4 import BeautifulSoup
import pytz

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Anthropic API for conversational features
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

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
    week_dates = get_week_dates()
    
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
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Week of {week_dates[0].strftime('%B %d')} - {week_dates[6].strftime('%B %d, %Y')}"
                }
            ]
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*Weekly Goal:* 5 workouts\n• 1 barre3 🩰\n• 1 solidcore 💪\n• 1 Cycle Sanctuary 🚴\n• 1-2 runs 🏃 (Saturday Greenlake + weekday solo)\n• 1 swim 🏊 (every other week)"
            }
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📅 This Week's Schedule*"
            }
        }
    ]
    
    # Add each day with workout options
    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    
    for i, date in enumerate(week_dates):
        day_key = date.strftime("%Y-%m-%d")
        day_workout = user_workouts.get(day_key, {})
        
        workout_text = "No workout planned"
        if day_workout:
            studio = day_workout.get("studio", "")
            time = day_workout.get("time", "")
            workout_text = f"{STUDIOS.get(studio, {}).get('emoji', '✨')} {STUDIOS.get(studio, {}).get('name', studio)} {time}"
        
        # Saturday is special - Greenlake running group
        if i == 5:  # Saturday
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{day_names[i]} ({date.strftime('%m/%d')})*\n{workout_text}\n_🏃 Greenlake Running Group meets Saturday mornings_"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Plan Day", "emoji": True},
                    "action_id": f"plan_day_{day_key}",
                    "value": day_key
                }
            })
        else:
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*{day_names[i]} ({date.strftime('%m/%d')})*\n{workout_text}"
                },
                "accessory": {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Plan Day", "emoji": True},
                    "action_id": f"plan_day_{day_key}",
                    "value": day_key
                }
            })
    
    # Add booking reminders
    reminders = []
    for studio_key in ["solidcore", "barre3", "cycle"]:
        reminder = get_booking_reminder(studio_key)
        if reminder:
            reminders.append(reminder)
    
    if reminders:
        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*🔔 Booking Reminders*\n" + "\n".join(reminders)
            }
        })
    
    # Add quick actions
    blocks.extend([
        {"type": "divider"},
        {
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
                    "text": {"type": "plain_text", "text": "☀️ Check Weather", "emoji": True},
                    "action_id": "check_weather"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📋 View Schedules", "emoji": True},
                    "action_id": "view_schedules"
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "📊 My Calendar", "emoji": True},
                    "action_id": "view_calendar"
                }
            ]
        }
    ])
    
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
                    "placeholder": {"type": "plain_text", "text": "Class name, instructor, etc."}
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
            "block_id": "notes",
            "optional": True,
            "element": {
                "type": "plain_text_input",
                "action_id": "notes",
                "multiline": True,
                "placeholder": {"type": "plain_text", "text": "Any other preferences or constraints..."}
            },
            "label": {"type": "plain_text", "text": "Additional notes"}
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
    """Handle click on 'My Calendar' button - prompts to check Google Calendar."""
    await ack()
    
    await client.views_open(
        trigger_id=body["trigger_id"],
        view={
            "type": "modal",
            "title": {"type": "plain_text", "text": "Calendar Integration"},
            "close": {"type": "plain_text", "text": "Close"},
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn", 
                        "text": "📅 *Calendar Integration*\n\nTo check your work calendar availability, you can:\n\n1. Use `/workout-plan check-calendar` to see busy times\n2. Connect Google Calendar in the app settings\n\n_Tip: Tell me your busy days when planning your week!_"
                    }
                }
            ]
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
    notes = values.get("notes_input", {}).get("notes", {}).get("value", "")
    
    # Save to user data
    if user_id not in user_data:
        user_data[user_id] = {"workouts": {}}
    
    user_data[user_id]["workouts"][day_key] = {
        "studio": studio,
        "time": time,
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
    notes = values.get("notes", {}).get("notes", {}).get("value", "")
    
    # Extract daily time preferences if present
    daily_prefs = {}
    if has_daily_times:
        for block_id, block_data in values.items():
            if block_id.startswith("day_time_"):
                day_key = block_id.replace("day_time_", "")
                selected = block_data.get("day_pref", {}).get("selected_option")
                if selected:
                    daily_prefs[day_key] = selected["value"]
    
    # Generate suggested plan
    suggested_plan = generate_week_plan(unavailable, preferred_time, include_swim, daily_prefs if daily_prefs else None)
    
    # Send plan as DM (without booking reminders)
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
    
    await client.chat_postMessage(
        channel=user_id,
        text="✅ Plan applied! Check your App Home to see your schedule."
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
    
    # Get current week info
    week_dates = get_week_dates(planning_mode=True)
    today = datetime.now(SEATTLE_TZ)
    
    # Format current schedule for Claude
    schedule_text = ""
    for date in week_dates:
        day_key = date.strftime("%Y-%m-%d")
        day_name = date.strftime("%A, %m/%d")
        workout = current_schedule.get(day_key)
        if workout:
            studio = workout["studio"]
            time = workout["time"]
            name = STUDIOS.get(studio, {}).get("name", studio)
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
    
    system_prompt = f"""You are a helpful workout planning assistant for a family fitness planner. Today is {today.strftime("%A, %B %d, %Y")}.

The user's current workout schedule for the week of {week_dates[0].strftime("%B %d")} - {week_dates[6].strftime("%B %d")}:
{schedule_text}

{studios_info}

Weekly goals: 5 workouts total (1 barre3, 1 solidcore, 1 Cycle Sanctuary, 1-2 runs, optional swim)

Your job:
1. Understand what the user wants to do with their schedule
2. If they want to make changes (move, add, remove, swap workouts), output a JSON block with the changes
3. Be friendly and conversational

IMPORTANT: If making schedule changes, you MUST include a JSON block in your response like this:
```json
{{"action": "update", "changes": {{"YYYY-MM-DD": {{"studio": "studio_key", "time": "HH:MM", "notes": "optional"}}, "YYYY-MM-DD": null}}}}
```
- Use null to remove a workout from a day
- Use the studio keys exactly: barre3, solidcore, cycle, pool, greenlake, solo_run
- Use 24-hour time format (e.g., "13:00" for 1 PM, "17:30" for 5:30 PM)

If NOT making changes (just answering questions), don't include any JSON block.

Keep responses concise and friendly."""

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
    """Fetch current Seattle weather."""
    # In production, this would call a weather API
    # For now, return placeholder
    return """
☀️ *Seattle Weather*

🌡️ Today: 52°F / Partly Cloudy
💨 Wind: 8 mph
🌧️ Rain chance: 30%

*This Week:*
• Mon: 54°F ☁️
• Tue: 51°F 🌧️
• Wed: 49°F 🌧️
• Thu: 53°F ⛅
• Fri: 55°F ☀️
• Sat: 52°F ⛅ _(Good for Greenlake run!)_
• Sun: 50°F ☁️

_Perfect weather for indoor workouts if it rains!_
"""


# Main entry point
async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())