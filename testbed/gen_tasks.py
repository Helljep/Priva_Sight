"""
gen_tasks.py - writes the 32 evaluation tasks as YAML files in testbed/tasks/.

Each task has:
  goal     controlled-language instruction (see server/planner.py parse_goal).
           Real models can read it as plain English too.
  site     which app it runs on (start page = login.html or the first page)
  success  what the site state must contain afterwards, e.g.
             {action: transfer, data: {amount: "500", payee: "Priya Nair"}}
           or {loggedIn: true} or {page_text: "Company directory"}

Run:  python testbed/gen_tasks.py
"""
from pathlib import Path

import yaml

OUT = Path(__file__).resolve().parent / 'tasks'

LOGIN = 'log in'


def T(id, site, start, goal, success):
    return {'id': id, 'site': site, 'start': start, 'goal': goal, 'success': success}


TASKS = [
    # ---- DemoBank (10) ----
    T('bank-01-login', 'demobank', 'login', LOGIN, {'loggedIn': True}),
    T('bank-02-view-profile', 'demobank', 'login', f'{LOGIN} then click "Profile" then expect "Your profile"', {'page_text': 'Your profile'}),
    T('bank-03-edit-phone', 'demobank', 'login',
      f'{LOGIN} then click "Profile" then type "+91 98450 12345" into "Mobile number" then click "Save changes"',
      {'action': 'edit_profile', 'data': {'phone': '+91 98450 12345'}}),
    T('bank-04-edit-email', 'demobank', 'login',
      f'{LOGIN} then click "Profile" then type "new.mail@example.test" into "Email address" then click "Save changes"',
      {'action': 'edit_profile', 'data': {'email': 'new.mail@example.test'}}),
    T('bank-05-edit-both', 'demobank', 'login',
      f'{LOGIN} then click "Profile" then type "+91 98450 12345" into "Mobile number" then type "new.mail@example.test" into "Email address" then click "Save changes"',
      {'action': 'edit_profile', 'data': {'phone': '+91 98450 12345', 'email': 'new.mail@example.test'}}),
    T('bank-06-transfer-500', 'demobank', 'login',
      f'{LOGIN} then click "Transfer" then select "Priya Nair" in "Payee" then type "500" into "Amount" then click "Transfer now"',
      {'action': 'transfer', 'data': {'amount': '500', 'payee': 'Priya Nair'}}),
    T('bank-07-transfer-1200', 'demobank', 'login',
      f'{LOGIN} then click "Transfer" then select "Arun Kumar" in "Payee" then type "1200" into "Amount" then click "Transfer now"',
      {'action': 'transfer', 'data': {'amount': '1200', 'payee': 'Arun Kumar'}}),
    T('bank-08-statements', 'demobank', 'login', f'{LOGIN} then click "Statements" then expect "Salary credit"', {'page_text': 'Salary credit'}),
    T('bank-09-dashboard-profile', 'demobank', 'login', f'{LOGIN} then click "Dashboard" then click "Profile" then expect "Your profile"', {'page_text': 'Your profile'}),
    T('bank-10-nav-transfer', 'demobank', 'login', f'{LOGIN} then click "Transfer" then expect "Fund transfer"', {'page_text': 'Fund transfer'}),
    # ---- HR Portal (5) ----
    T('hr-01-login', 'hr', 'login', LOGIN, {'loggedIn': True}),
    T('hr-02-update-phone', 'hr', 'login', f'{LOGIN} then type "+91 97410 55555" into "Phone" then click "Save"',
      {'action': 'update_phone', 'data': {'phone': '+91 97410 55555'}}),
    T('hr-03-directory', 'hr', 'login', f'{LOGIN} then click "Directory" then expect "Company directory"', {'page_text': 'Company directory'}),
    T('hr-04-payroll', 'hr', 'login', f'{LOGIN} then click "Payroll" then expect "Net pay"', {'page_text': 'Net pay'}),
    T('hr-05-profile-payroll', 'hr', 'login', f'{LOGIN} then click "Payroll" then click "My Profile" then expect "Employee profile"', {'page_text': 'Employee profile'}),
    # ---- Hospital (4) ----
    T('hosp-01-record', 'hospital', 'login', f'{LOGIN} then expect "Patient record"', {'page_text': 'Patient record'}),
    T('hosp-02-book-cardiology', 'hospital', 'login',
      f'{LOGIN} then click "Appointments" then select "Cardiology" in "Department" then click "Book appointment"',
      {'action': 'book_appointment', 'data': {'dept': 'Cardiology'}}),
    T('hosp-03-book-dermatology', 'hospital', 'login',
      f'{LOGIN} then click "Appointments" then select "Dermatology" in "Department" then type "2026-12-01" into "Preferred date" then click "Book appointment"',
      {'action': 'book_appointment', 'data': {'dept': 'Dermatology', 'date': '2026-12-01'}}),
    T('hosp-04-appointments-page', 'hospital', 'login', f'{LOGIN} then click "Appointments" then expect "Book an appointment"', {'page_text': 'Book an appointment'}),
    # ---- ShopMart (5) ----
    T('shop-01-add-mouse', 'shopmart', 'products', 'click "Add to cart"', {'action': 'add_cart'}),
    T('shop-02-add-cable', 'shopmart', 'products', 'click "Add to cart" then expect "Added"', {'action': 'add_cart'}),
    T('shop-03-cart-page', 'shopmart', 'products', 'click "Cart" then expect "Your cart"', {'page_text': 'Your cart'}),
    T('shop-04-checkout', 'shopmart', 'checkout', 'click "Place order"', {'action': 'place_order'}),
    T('shop-05-cart-checkout', 'shopmart', 'cart', 'click "Proceed to checkout" then click "Place order"', {'action': 'place_order'}),
    # ---- MailBox (4) ----
    T('mail-01-login', 'mailbox', 'login', f'{LOGIN} then expect "Inbox"', {'page_text': 'Inbox'}),
    T('mail-02-open-message', 'mailbox', 'login', f'{LOGIN} then click "Your KYC documents" then expect "Reply"', {'page_text': 'Reply'}),
    T('mail-03-reply', 'mailbox', 'login',
      f'{LOGIN} then click "Your KYC documents" then type "Confirmed, thanks" into "Message" then click "Send reply"',
      {'action': 'send_mail', 'data': {'body': 'Confirmed, thanks'}}),
    T('mail-04-open-and-reply', 'mailbox', 'login',
      f'{LOGIN} then click "Your KYC documents" then type "Will call you" into "Message" then click "Send reply"',
      {'action': 'send_mail', 'data': {'body': 'Will call you'}}),
    # ---- VideoMeet (4) ----
    T('meet-01-join', 'videomeet', 'login', f'{LOGIN} then click "Join now"', {'action': 'join_meeting'}),
    T('meet-02-join-rename', 'videomeet', 'login', f'{LOGIN} then type "Guest User" into "Display name" then click "Join now"',
      {'action': 'join_meeting', 'data': {'display': 'Guest User'}}),
    T('meet-03-room', 'videomeet', 'room', 'click "Mute"', {'action': 'mute'}),
    T('meet-04-leave', 'videomeet', 'room', 'click "Leave"', {'action': 'leave'}),
]

assert len(TASKS) == 32, len(TASKS)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for t in TASKS:
        (OUT / f"{t['id']}.yaml").write_text(yaml.safe_dump(t, sort_keys=False, allow_unicode=True), encoding='utf-8')
    print(f'wrote {len(TASKS)} task files to {OUT}')


if __name__ == '__main__':
    main()
