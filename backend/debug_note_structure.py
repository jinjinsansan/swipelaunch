#!/usr/bin/env python3
"""Debug script to check note structure in database"""

import json
from app.config import settings
from supabase import create_client

def main():
    supabase = create_client(settings.supabase_url, settings.supabase_key)
    
    # Get first 3 notes with content
    response = supabase.table('notes').select('id, title, content_blocks').limit(5).execute()
    
    if not response.data:
        print("No notes found in database")
        return
    
    for note in response.data:
        print(f"\n{'='*80}")
        print(f"NOTE ID: {note['id']}")
        print(f"Title: {note['title']}")
        
        content_blocks = note.get('content_blocks') or []
        print(f"\nTotal blocks: {len(content_blocks)}")
        
        # Show first 3 blocks
        for i, block in enumerate(content_blocks[:3]):
            print(f"\n--- Block {i} ---")
            print(f"Type: {block.get('type')}")
            print(f"Access: {block.get('access')}")
            print(f"Data keys: {list(block.get('data', {}).keys())}")
            
            # Show data structure
            data = block.get('data', {})
            if data:
                print(f"\nData content:")
                for key, value in data.items():
                    if isinstance(value, str):
                        # Truncate long strings
                        display_value = value[:100] + '...' if len(value) > 100 else value
                        print(f"  {key}: {repr(display_value)}")
                    elif isinstance(value, list):
                        print(f"  {key}: [list with {len(value)} items]")
                        if value and len(value) > 0:
                            print(f"    First item: {json.dumps(value[0], ensure_ascii=False)[:200]}")
                    else:
                        print(f"  {key}: {type(value).__name__} = {value}")

if __name__ == '__main__':
    main()
