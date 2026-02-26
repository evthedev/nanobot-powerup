# Recommendation Enhancement Skill

## Purpose
Enhance recommendation capabilities by incorporating user preferences, calendar events, and weather conditions to provide a well-rounded suggestion — with screenshot citations of all key research sources.

## Features
- Considers user's calendar for scheduling conflicts
- Checks weather conditions for outdoor events
- Takes into account user preferences for tailored recommendations
- **Screenshot capture** of cited research sources (booking sites, event pages, venue info) using Playwright
- Visual evidence attached to all recommendations for transparency

## Screenshot Capture (Updated 2026-02-24)
When providing recommendations that cite web sources, this skill now:
1. Navigates to each cited URL using the Playwright browser tool
2. Takes a full-page or viewport screenshot of the source
3. Saves screenshots to `/Users/ev/.nanobot/workspace/skills/travel-research/screenshots/`
4. Attaches screenshots to the final recommendation message via the `message` tool

## Usage
This skill automatically integrates with the recommendation process to ensure suggestions are aligned with the user's schedule, weather, and preferences.

For travel recommendations, this skill works in conjunction with the **travel-research** skill to provide:
- Flight options with booking site screenshots
- Accommodation options with hotel site screenshots
- Event/venue information with official site screenshots
- Itinerary pages with map/guide screenshots

## Example
When recommending a BTS concert trip to Busan, the skill will:
- Check the user's calendar for conflicts
- Verify weather conditions for the travel dates
- Research flights from Perth to Busan (screenshot: Skyscanner/Google Flights)
- Research hotels near the venue (screenshot: Booking.com/Agoda)
- Capture the concert venue page (screenshot: official site)
- Send the full plan with attached screenshots

## How to Update Preferences
User preferences can be updated in the memory file to reflect changes in interests or priorities. This ensures that future recommendations remain relevant and personalized.
