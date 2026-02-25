from SmartApi import SmartConnect
import pyotp

def test_login():
    api_key = "jeCM89TR"
    client_code = "P306112"
    password = "0673"
    totp_secret = "WF75HNPE7V4YJRXFEFG6LLNHBM"
    
    smartApi = SmartConnect(api_key=api_key)
    try:
        totp = pyotp.TOTP(totp_secret).now()
        data = smartApi.generateSession(client_code, password, totp)
        print("Login Result:", data)
        refreshToken = data['data']['refreshToken']
        feedToken = smartApi.getfeedToken()
        print("Got tokens successfully!")
        
        # Now let's try to get profile or search for HDFCBANK 
        profile = smartApi.getProfile(refreshToken)
        print("Profile Name:", profile['data']['name'])
        
    except Exception as e:
        print("Login Error:", e)

if __name__ == "__main__":
    test_login()
