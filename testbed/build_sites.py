"""
build_sites.py - writes the six synthetic web apps (19 pages) into testbed/sites/.

  demobank   DemoBank   login, dashboard, profile, transfer, statements
  hr         HR Portal  login, profile, directory, payroll
  hospital   Hospital   login, record, appointments
  shopmart   ShopMart   products, cart, checkout
  mailbox    MailBox    inbox, message
  videomeet  VideoMeet  lobby, room

All personal data on these pages is filled in at run time from the synthetic
personas by common/site.js, so the pages here are plain templates.
Run:  python testbed/build_sites.py
"""
from pathlib import Path

OUT = Path(__file__).resolve().parent / 'sites'

SITES = {
    'demobank': ('DemoBank', [('dashboard', 'Dashboard'), ('profile', 'Profile'), ('transfer', 'Transfer'), ('statements', 'Statements')]),
    'hr': ('HR Portal', [('profile', 'My Profile'), ('directory', 'Directory'), ('payroll', 'Payroll')]),
    'hospital': ('City Hospital', [('record', 'My Record'), ('appointments', 'Appointments')]),
    'shopmart': ('ShopMart', [('products', 'Products'), ('cart', 'Cart'), ('checkout', 'Checkout')]),
    'mailbox': ('MailBox', [('inbox', 'Inbox'), ('message', 'Message')]),
    'videomeet': ('VideoMeet', [('lobby', 'Lobby'), ('room', 'Room')]),
}


def row(label, field, pii=None):
    return f'<div class="row"><span class="k">{label}</span><span class="v" data-bind="{field}"></span></div>'


def page(site, name, title, body, login_required=True):
    brand, nav = SITES[site]
    links = ''.join(f'<a href="{n}.html">{t}</a>' for n, t in nav)
    logout = '<a href="login.html" data-logout>Log out</a>' if login_required and (site, 'login') != (site, name) else ''
    guard = ' data-requires-login' if login_required else ''
    html = f'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{brand} - {title}</title><link rel="stylesheet" href="/common/site.css"></head>
<body data-site="{site}"{guard}>
<header class="top"><span class="brand">{brand}</span>{links}{logout}</header>
<main>
{body}
</main>
<script src="/common/site.js"></script>
</body></html>
'''
    d = OUT / site
    d.mkdir(parents=True, exist_ok=True)
    (d / f'{name}.html').write_text(html, encoding='utf-8')


def login(site, next_page, heading):
    page(site, 'login', 'Log in', f'''<section class="card"><h1>{heading}</h1>
<form data-login data-next="{next_page}.html">
<label for="username">Username</label><input id="username" name="username" autocomplete="username">
<label for="password">Password</label><input id="password" name="password" type="password" autocomplete="current-password">
<button type="submit">Log in</button><div id="error" class="error"></div></form></section>''', login_required=False)


def build():
    # ---------------- DemoBank ----------------
    login('demobank', 'dashboard', 'DemoBank Net Banking')
    page('demobank', 'dashboard', 'Dashboard', f'''
<section class="card"><h1>Welcome, <span data-bind="name"></span></h1>
{row('Account no.', 'account')}{row('IFSC', 'ifsc')}{row('Balance', 'balance')}</section>
<section class="card"><h2>Registered contact</h2>{row('Mobile', 'phone')}{row('Email', 'email')}</section>''')
    page('demobank', 'profile', 'Profile', f'''
<section class="card"><h1>Your profile</h1>
{row('Name', 'name')}{row('Date of birth', 'dob')}{row('Aadhaar', 'aadhaar')}{row('PAN', 'pan')}
{row('Address', 'address')}{row('Card', 'card')}</section>
<section class="card"><h2>Edit contact details</h2>
<form data-action="edit_profile" data-success="Profile updated">
<label for="phone">Mobile number</label><input id="phone" name="phone" data-bind-value="phone">
<label for="email">Email address</label><input id="email" name="email" data-bind-value="email">
<button type="submit">Save changes</button></form><div id="result"></div></section>''')
    page('demobank', 'transfer', 'Transfer', '''
<section class="card"><h1>Fund transfer</h1>
<form data-action="transfer" data-success="Transfer successful">
<label for="payee">Payee</label><select id="payee" name="payee"><option>Priya Nair</option><option>Arun Kumar</option></select>
<label for="amount">Amount (INR)</label><input id="amount" name="amount" inputmode="numeric">
<button type="submit">Transfer now</button></form><div id="result"></div>
<p>Saved payee: <span data-pii="NAME">Priya Nair</span></p></section>''')
    page('demobank', 'statements', 'Statements', f'''
<section class="card"><h1>Statement</h1><p>Account <span data-bind="account"></span> - <span data-bind="name"></span></p>
<table><tr><th>Date</th><th>Description</th><th>Amount</th></tr>
<tr><td>02/10/2026</td><td>UPI to <span data-pii="NAME">Priya Nair</span></td><td>-1,200</td></tr>
<tr><td>05/10/2026</td><td>Salary credit</td><td>+54,000</td></tr>
<tr><td>09/10/2026</td><td>Electricity bill</td><td>-2,340</td></tr></table></section>''')

    # ---------------- HR Portal ----------------
    login('hr', 'profile', 'HR Portal Sign in')
    page('hr', 'profile', 'My profile', f'''
<section class="card"><h1>Employee profile</h1><img class="avatar" data-face alt="profile photo">
{row('Name', 'name')}{row('Department', 'department')}{row('Email', 'email')}{row('Phone', 'phone')}{row('Address', 'address')}</section>
<section class="card"><h2>Update phone</h2><form data-action="update_phone" data-success="Phone updated">
<label for="phone">Phone</label><input id="phone" name="phone" data-bind-value="phone"><button type="submit">Save</button></form><div id="result"></div></section>''')
    page('hr', 'directory', 'Directory', '''
<section class="card"><h1>Company directory</h1><div class="grid">
<div class="tile"><img class="avatar" data-face data-of="0" alt="photo"><div data-bind="name" data-of="0"></div><small data-bind="department" data-of="0"></small></div>
<div class="tile"><img class="avatar" data-face data-of="1" alt="photo"><div data-bind="name" data-of="1"></div><small data-bind="department" data-of="1"></small></div>
<div class="tile"><img class="avatar" data-face data-of="2" alt="photo"><div data-bind="name" data-of="2"></div><small data-bind="department" data-of="2"></small></div>
</div></section>''')
    page('hr', 'payroll', 'Payroll', f'''
<section class="card"><h1>Payroll</h1>{row('Employee', 'name')}{row('PAN', 'pan')}{row('Bank account', 'account')}{row('IFSC', 'ifsc')}
<table><tr><th>Month</th><th>Net pay</th></tr><tr><td>September</td><td>54,000</td></tr><tr><td>October</td><td>54,000</td></tr></table></section>''')

    # ---------------- Hospital ----------------
    login('hospital', 'record', 'Patient Portal')
    page('hospital', 'record', 'My record', f'''
<section class="card"><h1>Patient record</h1><img class="avatar" data-face alt="patient photo">
{row('Patient', 'name')}{row('Date of birth', 'dob')}{row('Aadhaar', 'aadhaar')}{row('Mobile', 'phone')}{row('Address', 'address')}
{row('Condition', 'condition')}{row('Doctor', 'doctor')}</section>''')
    page('hospital', 'appointments', 'Appointments', '''
<section class="card"><h1>Book an appointment</h1>
<form data-action="book_appointment" data-success="Appointment booked">
<label for="dept">Department</label><select id="dept" name="dept"><option>General Medicine</option><option>Cardiology</option><option>Dermatology</option></select>
<label for="date">Preferred date</label><input id="date" name="date" placeholder="2026-12-01">
<button type="submit">Book appointment</button></form><div id="result"></div>
<p>Next visit with <span data-pii="NAME">Dr. Menon</span></p></section>''')

    # ---------------- ShopMart ----------------
    page('shopmart', 'products', 'Products', '''
<section class="card"><h1>Products</h1><table>
<tr><td>Wireless Mouse</td><td>799</td><td><button data-click-action="add_cart" data-item="Wireless Mouse" data-success="Added Wireless Mouse to cart">Add to cart</button></td></tr>
<tr><td>USB-C Cable</td><td>299</td><td><button data-click-action="add_cart" data-item="USB-C Cable" data-success="Added USB-C Cable to cart">Add to cart</button></td></tr>
<tr><td>Notebook</td><td>149</td><td><button data-click-action="add_cart" data-item="Notebook" data-success="Added Notebook to cart">Add to cart</button></td></tr>
</table><div id="result"></div></section>''', login_required=False)
    page('shopmart', 'cart', 'Cart', '''
<section class="card"><h1>Your cart</h1><p>Review items, then continue.</p><a class="btn" href="checkout.html">Proceed to checkout</a></section>''', login_required=False)
    page('shopmart', 'checkout', 'Checkout', '''
<section class="card"><h1>Checkout</h1>
<form data-action="place_order" data-success="Order placed">
<label for="fullname">Full name</label><input id="fullname" name="fullname" autocomplete="name" data-bind-value="name">
<label for="addr">Delivery address</label><input id="addr" name="address" autocomplete="street-address" data-bind-value="address">
<label for="phone">Phone</label><input id="phone" name="phone" autocomplete="tel" data-bind-value="phone">
<label for="card">Card number</label><input id="card" name="card" autocomplete="cc-number" data-bind-value="card">
<button type="submit">Place order</button></form><div id="result"></div></section>''', login_required=False)

    # ---------------- MailBox ----------------
    login('mailbox', 'inbox', 'MailBox Sign in')
    page('mailbox', 'inbox', 'Inbox', '''
<section class="card"><h1>Inbox</h1><table>
<tr><td data-bind="name" data-of="1"></td><td><a href="message.html">Your KYC documents</a></td></tr>
<tr><td data-bind="name" data-of="2"></td><td>Lunch on Friday?</td></tr>
<tr><td>Newsletter</td><td>October product updates</td></tr></table></section>''')
    page('mailbox', 'message', 'Message', '''
<section class="card"><h1>Your KYC documents</h1>
<p>From: <b data-bind="name" data-of="1"></b> (<span data-bind="email" data-of="1"></span>)</p>
<p>Hello <span data-bind="first"></span>, please confirm the Aadhaar <span data-bind="aadhaar"></span> and PAN <span data-bind="pan"></span> on file.
Call me on <span data-bind="phone" data-of="1"></span> if needed.</p></section>
<section class="card"><h2>Reply</h2><form data-action="send_mail" data-success="Message sent">
<label for="body">Message</label><textarea id="body" name="body" rows="3"></textarea><button type="submit">Send reply</button></form><div id="result"></div></section>''')

    # ---------------- VideoMeet ----------------
    login('videomeet', 'lobby', 'VideoMeet Sign in')
    page('videomeet', 'lobby', 'Lobby', '''
<section class="card"><h1>Ready to join?</h1><img class="avatar" data-face alt="your camera preview">
<form data-action="join_meeting" data-success="Joined meeting"><label for="display">Display name</label><input id="display" name="display" data-bind-value="name">
<button type="submit">Join now</button></form><div id="result"></div></section>''')
    page('videomeet', 'room', 'Room', '''
<section class="card"><h1>Team sync</h1><video data-face data-of="0" muted></video>
<div class="grid"><div class="tile"><img class="avatar" data-face data-of="3" alt="participant"><div data-bind="name" data-of="3"></div></div>
<div class="tile"><img class="avatar" data-face data-of="4" alt="participant"><div data-bind="name" data-of="4"></div></div></div>
<button data-click-action="mute" data-success="Muted">Mute</button> <button data-click-action="leave" data-success="Left meeting">Leave</button><div id="result"></div></section>''')

    n = sum(1 for _ in OUT.glob('*/*.html'))
    print(f'wrote {n} pages in {len(SITES)} sites under {OUT}')


if __name__ == '__main__':
    build()
