from nsepython import option_chain

def run_test():
    payload = option_chain("HDFCBANK")
    print(type(payload))
    if isinstance(payload, dict):
        print("Keys:", payload.keys())
        if 'records' in payload:
            print("Records count:", len(payload['records'].get('data', [])))

if __name__ == "__main__":
    run_test()
