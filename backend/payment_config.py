"""
Razorpay TEST MODE keys go here. This is real Razorpay, not a mock -
but running in test mode, so no real money ever moves and Razorpay
gives you fake card numbers to "pay" with.

How to get your own test keys (takes about 5 minutes, free):
1. Sign up at https://dashboard.razorpay.com/signup
2. Once logged in, check the toggle in the top-left corner says
   "Test Mode" (it usually defaults to this for a new account)
3. Go to Settings -> API Keys -> Generate Test Key
4. Copy the Key Id and Key Secret it shows you, paste them below

Test card number for the demo: 4111 1111 1111 1111, any future
expiry date, any CVV, any name. Razorpay's docs have more test
cards (for UPI, netbanking, etc.) if you want to try those too.

NEVER commit real LIVE keys here, and never push this file to a
public GitHub repo with real values filled in - add it to
.gitignore if your repo is public.
"""

RAZORPAY_KEY_ID = "rzp_test_your_key_id_here"
RAZORPAY_KEY_SECRET = "your_key_secret_here"


# "mock"     = demo checkout, works with no Razorpay account (default)
# "razorpay" = real Razorpay test mode - fill in the two keys above first
PAYMENT_MODE = "mock"
