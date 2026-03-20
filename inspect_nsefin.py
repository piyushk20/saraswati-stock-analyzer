from nsefin import NSEClient
import pprint

def inspect_nsefin():
    try:
        nse = NSEClient()
        print("Methods in NSEClient:")
        pprint.pprint([m for m in dir(nse) if not m.startswith("_")])
        
        # Test if there is an option chain method
        # Common names: get_option_chain, option_chain, get_options
        if hasattr(nse, "get_option_chain"):
            print("\nTesting get_option_chain for TCS:")
            pprint.pprint(nse.get_option_chain("TCS"))
        elif hasattr(nse, "get_options"):
            print("\nTesting get_options for TCS:")
            pprint.pprint(nse.get_options("TCS"))
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    inspect_nsefin()
