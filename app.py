from dotenv import load_dotenv
load_dotenv()

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


def get_week_dates(start_date: Optional[datetime] = None) -> list:
    """Get dates for the current or specified week (Monday-Sunday)."""
    if start_date is None:
        start_date = datetime.now(SEATTLE_TZ)
    
    # Find Monday of the week
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


def build_plan_week_modal() -> dict:
    """Build modal for AI-assisted week planning."""
    week_dates = get_week_dates()
    
    day_options = [
        {
            "text": {"type": "plain_text", "text": f"{date.strftime('%A (%m/%d)')}", "emoji": True},
            "value": date.strftime("%Y-%m-%d")
        }
        for date in week_dates
    ]
    
    return {
        "type": "modal",
        "callback_id": "plan_week_submit",
        "title": {"type": "plain_text", "text": "Plan My Week"},
        "submit": {"type": "plain_text", "text": "Generate Plan"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": [
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🗓️ Weekly Workout Planner", "emoji": True}
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
                "element": {
                    "type": "multi_static_select",
                    "action_id": "days",
                    "placeholder": {"type": "plain_text", "text": "Select days"},
                    "options": day_options
                },
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
                        {"text": {"type": "plain_text", "text": "🔄 Varies by day"}, "value": "varies"}
                    ]
                },
                "label": {"type": "plain_text", "text": "Preferred workout time"}
            },
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
        ]
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
@app.action({"action_id": "plan_day_*"})
async def handle_plan_day(ack, body, client: AsyncWebClient, action):
    """Handle click on 'Plan Day' button for any day."""
    await ack()
    
    day_key = action["value"]
    
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
    
    unavailable_days = values.get("unavailable_days", {}).get("days", {}).get("selected_options", [])
    unavailable = [opt["value"] for opt in unavailable_days] if unavailable_days else []
    
    preferred_time = values["preferred_times"]["time"]["selected_option"]["value"]
    include_swim = values["swim_week"]["swim"]["selected_option"]["value"] == "yes"
    notes = values.get("notes", {}).get("notes", {}).get("value", "")
    
    # Generate suggested plan
    suggested_plan = generate_week_plan(unavailable, preferred_time, include_swim)
    
    # Send plan as DM
    plan_message = format_plan_message(suggested_plan)
    
    await client.chat_postMessage(
        channel=user_id,
        text="Here's your suggested workout plan! 🏋️",
        blocks=[
            {
                "type": "header",
                "text": {"type": "plain_text", "text": "🗓️ Your Suggested Week", "emoji": True}
            },
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": plan_message}
            },
            {"type": "divider"},
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*📅 Booking Reminders:*\n• solidcore - Book on the 1st of the month\n• barre3 & Cycle Sanctuary - Book 1 week out\n• Greenlake Running Group - RSVP on Meetup"
                }
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


# Message handlers
@app.message("(?i)(workout|plan|schedule|class|gym)")
async def handle_workout_message(message, say, client: AsyncWebClient):
    """Respond to messages mentioning workouts."""
    user_id = message["user"]
    text = message["text"].lower()
    
    if "solidcore" in text:
        await say(
            f"💪 *solidcore Ballard*\n"
            f"📍 2425 NW Market St\n"
            f"🔗 <{STUDIOS['solidcore']['url']}|View Schedule>\n"
            f"📅 Booking opens on the 1st of each month!"
        )
    elif "barre" in text or "barre3" in text:
        await say(
            f"🩰 *barre3 Ballard*\n"
            f"📍 5333 Ballard Ave NW\n"
            f"🔗 <{STUDIOS['barre3']['url']}|View Schedule>\n"
            f"📅 Classes open 1 week in advance"
        )
    elif "cycle" in text or "cycling" in text:
        await say(
            f"🚴 *Cycle Sanctuary*\n"
            f"📍 2420 NW Market St\n"
            f"🔗 <{STUDIOS['cycle']['url']}|View Schedule>\n"
            f"📅 Classes open 1 week in advance"
        )
    elif "swim" in text or "pool" in text:
        await say(
            f"🏊 *Ballard Public Pool*\n"
            f"📍 1471 NW 67th St\n"
            f"🔗 <{STUDIOS['pool']['url']}|View Schedule>\n"
        )
    elif "run" in text or "greenlake" in text:
        await say(
            f"🏃 *Running Options:*\n"
            f"• *Greenlake Running Group* - Saturdays at Green Lake\n"
            f"  🔗 <{STUDIOS['greenlake']['url']}|Meetup Page>\n"
            f"• *Solo runs* - 3-5 miles on a weekday"
        )
    else:
        await say(
            "Would you like help planning your workouts? Try:\n"
            "• `/workout plan` - Plan your week\n"
            "• `/workout schedules` - View studio schedules\n"
            "• Or check the App Home tab!"
        )


# Helper functions
def generate_week_plan(unavailable: list, preferred_time: str, include_swim: bool) -> dict:
    """Generate a suggested workout plan based on preferences."""
    week_dates = get_week_dates()
    plan = {}
    
    # Time suggestions based on preference
    time_map = {
        "early": "06:00",
        "morning": "08:30",
        "midday": "12:00",
        "evening": "17:30",
        "varies": "09:00"
    }
    default_time = time_map.get(preferred_time, "09:00")
    
    # Get available days
    available_days = []
    saturday_key = None
    
    for date in week_dates:
        day_key = date.strftime("%Y-%m-%d")
        if day_key not in unavailable:
            available_days.append((date, day_key))
            if date.weekday() == 5:  # Saturday
                saturday_key = day_key
    
    # Assign workouts - ensure we hit 5 total
    assigned = []
    
    # Saturday is always Greenlake Running Group
    if saturday_key and saturday_key not in unavailable:
        plan[saturday_key] = {"studio": "greenlake", "time": "09:00", "notes": "Saturday morning run with Greenlake Running Group"}
        assigned.append("greenlake")
        available_days = [(d, k) for d, k in available_days if k != saturday_key]
    
    # Assign one of each required studio
    required = ["barre3", "solidcore", "cycle"]
    
    for studio in required:
        if available_days:
            date, day_key = available_days.pop(0)
            plan[day_key] = {"studio": studio, "time": default_time, "notes": ""}
            assigned.append(studio)
    
    # Add swim if requested
    if include_swim and available_days:
        date, day_key = available_days.pop(0)
        plan[day_key] = {"studio": "pool", "time": default_time, "notes": ""}
        assigned.append("pool")
    
    # If we need more workouts to hit 5, add a solo run
    if len(assigned) < 5 and available_days:
        # Find a weekday for solo run
        for date, day_key in available_days:
            if date.weekday() < 5:  # Weekday
                plan[day_key] = {"studio": "solo_run", "time": default_time, "notes": "3-5 mile run"}
                assigned.append("solo_run")
                break
    
    return plan


def format_plan_message(plan: dict) -> str:
    """Format a plan dictionary into a readable message."""
    week_dates = get_week_dates()
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
