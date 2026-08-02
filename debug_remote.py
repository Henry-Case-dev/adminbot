#!/usr/bin/env python3
"""Remote debug script for AdminBot."""
import sys
sys.path.insert(0, '/var/www/admin_bot')

from config.settings import settings

print("=== SETTINGS ===")
print(f"SLAVIC_PHOTO_INTERVAL: {settings.SLAVIC_PHOTO_INTERVAL}")
print(f"SLAVIC_PHOTO_PATH: {settings.SLAVIC_PHOTO_PATH}")
print(f"SLAVIK_USER_ID: {settings.SLAVIK_USER_ID}")
print(f"SLAVIC_PHOTO_INTERVAL > 0: {settings.SLAVIC_PHOTO_INTERVAL > 0}")

print("\n=== FILE CHECK ===")
from pathlib import Path
photo_path = Path(settings.SLAVIC_PHOTO_PATH)
if not photo_path.is_absolute():
    photo_path = Path('/var/www/admin_bot') / photo_path
print(f"Photo path: {photo_path}")
print(f"Photo exists: {photo_path.exists()}")

print("\n=== WAR ALERT IMPORT ===")
from handlers.war_alert import war_alert_router, war_keyword_handler, war_keyword_forward_handler, war_channel_repost_handler
print(f"Router name: {war_alert_router.name}")
# Count handlers
handlers_list = list(war_alert_router.message.handlers) if hasattr(war_alert_router.message, 'handlers') else []
print(f"Handlers count: {len(handlers_list)}")

print("\n=== SLAVIK IMPORT ===")
import handlers.slavik as slavik_module
print(f"_db is None: {slavik_module._db is None}")
print(f"setup_slavik exists: {hasattr(slavik_module, 'setup_slavik')}")

print("\n=== BOT STARTUP SIMULATION ===")
import asyncio
from services.database import DatabaseService

async def test_db():
    db = DatabaseService(settings.DB_PATH)
    await db.initialize()
    slavik_module.setup_slavik(db)
    print(f"After setup: _db is None: {slavik_module._db is None}")
    
    # Test slavic_photo_count_tick
    result = await db.slavic_photo_count_tick(-1001234567890, settings.SLAVIC_PHOTO_INTERVAL)
    print(f"slavic_photo_count_tick (first call): {result}")
    
    # Test 10 calls
    for i in range(9):
        result = await db.slavic_photo_count_tick(-1001234567890, settings.SLAVIC_PHOTO_INTERVAL)
    print(f"slavic_photo_count_tick (10th call): {result}")
    
    await db.close()

asyncio.run(test_db())
print("\n=== ALL CHECKS PASSED ===")
