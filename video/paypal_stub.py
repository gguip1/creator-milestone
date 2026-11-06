"""Rehearsal only: a local stand-in for the PayPal sandbox invoice page and checkout popup.

`record.py --stub-paypal prelogin|popup-login` routes https://www.sandbox.paypal.com/** to these pages, so the
live S6/S7 code (host checks, iframe click, popup, login cut, amount checks) runs end to end with no network.
The pages carry a visible "LOCAL STUB, NOT PAYPAL" strip. Shaped after the verified structure of the sandbox
invoice page: cookie banner with Close, a 'PayPal-paypal' iframe holding the button, a popup that goes to
/checkoutnow (login) and then /webapps/hermes ('Complete Purchase').
"""

INFO: dict[str, str] = {"number": "CM-STUB-1"}
STRIP = '<div style="background:#b91c1c;color:#fff;padding:4px 10px;font:600 13px sans-serif">LOCAL STUB, NOT PAYPAL</div>'

INVOICE = """<!doctype html><title>Invoice</title><body style="font:16px sans-serif;margin:0">{strip}
<div id=cb style="position:fixed;bottom:0;left:0;right:0;background:#222;color:#fff;padding:14px">We use cookies. <button onclick="document.getElementById('cb').remove()">Close</button></div>
<main style="max-width:760px;margin:30px auto;padding:0 20px">
<h1>Invoice {number}</h1><p id=state>Amount due: $100.00 USD</p>
<table border=1 cellpadding=8 style="border-collapse:collapse;width:100%">
<tr><td>Extra outfit</td><td>1 x $80.00</td><td>$80.00</td></tr>
<tr><td>Extra revision</td><td>1 x $20.00</td><td>$20.00</td></tr>
<tr><td colspan=2><b>Total</b></td><td><b>$100.00</b></td></tr></table>
<h3>Note to recipient</h3><p>Change order #1, billed under scope v2.</p>
<h3>Terms and conditions</h3><p>Scope v2: full-body illustration; revisions 3 included; usage personal streaming.</p>
<div style="margin-top:300px"><iframe title="PayPal-paypal" src="/stub/button" style="width:204px;height:35px;border:0"></iframe></div>
<div style="margin-top:12px"><iframe title="PayPal-card" src="/stub/card" style="width:204px;height:35px;border:0"></iframe></div>
<div style="height:400px"></div></main>
<script>addEventListener('message', e => { if (e.data === 'paid') document.getElementById('state').textContent = 'This invoice was paid. Amount due: $0.00'; });</script>"""

BUTTON = """<!doctype html><body style="margin:0"><button id=b style="width:204px;height:35px;background:#ffc439;border:0;border-radius:4px;font:700 15px sans-serif">PayPal</button>
<script>
// Only a trusted user click opens the popup, like the real Buttons frame.
b.addEventListener('click', e => { if (!e.isTrusted) return; window.open('/checkoutnow', 'pp', 'width=480,height=640');
  addEventListener('message', m => parent.postMessage(m.data, '*')); });
</script>"""

CHECKOUT = """<!doctype html><title>Log in to PayPal</title><body style="font:16px sans-serif;margin:0">{strip}
<script>if (document.cookie.includes('stub_auth=1')) location.replace('/webapps/hermes');</script>
<form style="padding:30px" onsubmit="document.cookie='stub_auth=1; path=/'; location.href='/webapps/hermes'; return false">
<h2>Log in</h2><label>Email or mobile number<br><input id=email type=text value="prefilled@example.com" aria-label="Email or mobile number"></label><br><br>
<label>Password<br><input id=password type=password aria-label="Password"></label><br><br><button id=btnLogin type=submit>Log In</button></form>"""

HERMES = """<!doctype html><title>PayPal Checkout</title><body style="font:16px sans-serif;margin:0">{strip}
<div style="padding:30px"><h2>Hi, Test Buyer!</h2><p>Total: $100.00 USD</p><label><input type=radio checked> PayPal balance</label><br><br>
<button onclick="opener && opener.postMessage('paid','*'); window.close()">Complete Purchase</button></div>"""

SIGNIN = """<!doctype html><title>Log in</title><body style="font:16px sans-serif">{strip}<form onsubmit="{set} location.href='/myaccount/summary'; return false">
<input id=email type=text><button id=btnNext type=button onclick="document.getElementById('pw').style.display='block'">Next</button>
<div id=pw style="display:none"><input id=password type=password><button id=btnLogin type=submit>Log In</button></div></form>"""


def installer(prelogin: bool):
    def route_all(route):
        path = route.request.url.split("paypal.com", 1)[1].split("?")[0].split("#")[0]
        pages = {
            "/invoice/p/": INVOICE, "/stub/button": BUTTON, "/stub/card": "<body>card</body>",
            "/checkoutnow": CHECKOUT, "/webapps/hermes": HERMES, "/myaccount/summary": "<body>ok</body>",
            "/signin": SIGNIN,
        }
        body = pages.get(path, "<body>stub</body>")
        for token, value in (("{strip}", STRIP), ("{number}", INFO["number"]),
                             ("{set}", "document.cookie='stub_auth=1; path=/';" if prelogin else "")):
            body = body.replace(token, value)
        route.fulfill(status=200, content_type="text/html", body=body)

    def hook(ctx):
        ctx.route("https://www.sandbox.paypal.com/**", route_all)
    return hook
