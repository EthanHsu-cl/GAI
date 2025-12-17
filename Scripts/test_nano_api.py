"""Quick test script to verify Nano Banana API response structure."""
from gradio_client import Client

def test_case(client, prompt, description):
    """Test a specific case and print results."""
    print("\n" + "=" * 80)
    print(f"TEST: {description}")
    print("=" * 80)
    print(f"Prompt: {prompt}")
    
    try:
        result = client.predict(
            prompt=prompt,
            image1="",
            image2="",
            image3="",
            api_name="/nano_banana"
        )
        
        print(f"\nResult Type: {type(result)}")
        print(f"Result Length: {len(result)}")
        
        response_id, error_msg, response_data = result[:3]
        
        print(f"\n[0] Response ID: {response_id}")
        print(f"[1] Error Message: '{error_msg}'")
        print(f"[2] Response Data Type: {type(response_data)}")
        print(f"[2] Response Data: {response_data}")
        
        # Check for different failure patterns
        if error_msg:
            print(f"\n⚠️  ERROR MSG DETECTED: {error_msg}")
        
        if response_data and isinstance(response_data, list):
            for item in response_data:
                if isinstance(item, dict):
                    data_type = item.get('type', '')
                    data_content = item.get('data', '')
                    print(f"\n📦 Item type: {data_type}, data: {data_content[:50] if isinstance(data_content, str) else data_content}")
                    
                    if data_type == 'Text':
                        print(f"⚠️  TEXT RESPONSE DETECTED (likely failure): {data_content}")
        
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()

def test_nano_banana_api():
    """Test the Nano Banana API with various cases."""
    client = Client("http://192.168.31.40:8000/image_generation/")
    
    # Test Case 1: Blocked content
    test_case(client, "naked person", "Blocked/Moderated Content")
    
    # Test Case 2: Valid prompt
    test_case(client, "a beautiful sunset over mountains", "Valid Generation")
    
    # Test Case 3: Empty prompt
    test_case(client, "", "Empty Prompt")
    
    # Test Case 4: Very long prompt
    test_case(client, "a " * 500, "Very Long Prompt")
    
    print("\n" + "=" * 80)

if __name__ == "__main__":
    test_nano_banana_api()
