#!/usr/bin/env python3
"""Rehearsal-only Chromium smoke test of the Mini App at phone width.

Requires: pip install playwright, then playwright install chromium (or set CHROMIUM_PATH).
Normal mode drives a running local demo server over HTTP and refuses any non-demo target.
--bridge routes the browser's requests to an in-process ASGI app instead. It is for
environments where the browser cannot reach localhost, and it does not test HTTP,
cookies or TLS.
"""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import httpx
from playwright.sync_api import Page, expect, sync_playwright

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'src'))
parser = argparse.ArgumentParser(description='Rehearsal-only Chromium smoke test; --bridge does not test browser networking')
parser.add_argument('--bridge', action='store_true', help='Route browser requests to an in-process ASGI app')
parser.add_argument('--url', default='http://127.0.0.1:8000')
args = parser.parse_args()
base = args.url.rstrip('/')

PHONE = {'width': 390, 'height': 844}
out = root / 'artifacts'
out.mkdir(exist_ok=True)


def bridge_backend():
    from fastapi.testclient import TestClient

    from wedding_ops.api import create_app
    from wedding_ops.clock import DemoClock
    from wedding_ops.config import Settings
    from wedding_ops.db import Database
    from wedding_ops.seed import DEMO_TIME, seed_demo
    folder = tempfile.mkdtemp()
    db = Database(f'sqlite:///{folder}/ui.db')
    db.create_schema()
    seed_demo(db)
    settings = Settings(mode='demo', public_url=base)
    return TestClient(create_app(settings, db, DemoClock(DEMO_TIME)), base_url=base)


def switch_to(page: Page, name: str) -> None:
    """Rehearsal only: open the switch-person sheet from the top bar and pick someone."""
    page.get_by_role('button', name='Rehearsal:', exact=False).click()
    page.get_by_role('dialog').get_by_role('button', name=name, exact=False).first.click()
    expect(page.get_by_text(name, exact=False).first).to_be_visible()
    expect(page.get_by_role('dialog')).to_have_count(0)


def tab(page: Page, name: str) -> None:
    page.get_by_role('navigation', name='Sections').get_by_role('button', name=name, exact=False).click()


def home_tile(page: Page, name: str) -> None:
    tab(page, 'Home')
    page.locator('.tile', has_text=name).first.click()


def sheet(page: Page):
    return page.get_by_role('dialog')


def no_overflow(page: Page, where: str) -> None:
    assert not page.evaluate('document.documentElement.scrollWidth > window.innerWidth'), f'Horizontal overflow on {where}'


with sync_playwright() as playwright:
    binary = os.getenv('CHROMIUM_PATH')
    browser = playwright.chromium.launch(**({'executable_path': binary} if binary else {}), headless=True,
                                         args=['--no-sandbox', '--disable-dev-shm-usage'])
    page = browser.new_page(viewport=PHONE, device_scale_factor=2)
    page.route('https://telegram.org/**', lambda route: route.abort())
    errors: list[str] = []
    page.on('pageerror', lambda exc: errors.append(str(exc)))
    if args.bridge:
        backend = bridge_backend()

        def forward(route):
            request = route.request
            headers = {k: v for k, v in request.headers.items() if k.lower() not in {'host', 'content-length'}}
            response = backend.request(request.method, request.url.replace(base, ''), content=request.post_data_buffer, headers=headers)
            route.fulfill(status=response.status_code, body=response.content,
                          headers={k: v for k, v in response.headers.items() if k.lower() != 'content-length'})
        page.route(f'{base}/**', forward)
    else:
        config = httpx.get(base + '/api/config', timeout=10).json()
        if config.get('demo') is not True:
            raise RuntimeError('Refusing to run mutation tests against a non-demo site')
    page.goto(base, wait_until='networkidle')

    # Coordinator: Home hub, every tab and every hub section.
    page.get_by_role('button', name='Alex Morgan', exact=False).click()
    expect(page.locator('.tile', has_text='Review')).to_be_visible()
    page.screenshot(path=str(out / 'mobile-coordinator-home.png'))
    for name in ['Schedule', 'Review', 'Crew', 'Guests']:
        tab(page, name)
        page.wait_for_timeout(150)
        no_overflow(page, name)
    for name in ['Places', 'Venue notes', 'Set up', 'Activity log']:
        home_tile(page, name)
        expect(page.get_by_role('button', name='Home', exact=True).first).to_be_visible()
        no_overflow(page, name)
    assert not errors, errors

    # Banquet reports a delay from the schedule. Only the coordinator can decide it.
    switch_to(page, 'Chris Wong')
    tab(page, 'Schedule')
    page.get_by_role('button', name='Dinner service', exact=False).click()
    sheet(page).get_by_role('button', name='Report a delay', exact=True).click()
    sheet(page).get_by_role('radio', name='15 min', exact=True).check()
    sheet(page).get_by_label('Why?', exact=False).fill('Second oven is slow.')
    sheet(page).get_by_role('button', name='Send to coordinator', exact=True).click()
    expect(page.get_by_text('Sent to the coordinator for a decision.')).to_be_visible()
    tab(page, 'My jobs')
    expect(page.get_by_text('Delays you reported')).to_be_visible()
    assert page.get_by_role('button', name='Approve', exact=True).count() == 0

    # Coordinator decides with the reporter's words and the before-and-after times.
    switch_to(page, 'Alex Morgan')
    expect(page.locator('.tile', has_text='Review')).to_contain_text('1 change')
    tab(page, 'Review')
    page.get_by_role('button', name='Dinner service', exact=False).first.click()
    expect(sheet(page).get_by_text('“Second oven is slow.”', exact=False)).to_be_visible()
    page.screenshot(path=str(out / 'mobile-approval.png'))
    sheet(page).get_by_role('button', name='Approve', exact=True).click()
    expect(page.get_by_text('Approved. The schedule is updated', exact=False)).to_be_visible()
    tab(page, 'Schedule')
    expect(page.get_by_text('+15 min', exact=True).first).to_be_visible()

    # Coordinator sends an update; the usher reads it; the coordinator sees who read it.
    # The rehearsal clock is frozen, so move it on first; otherwise this update and the
    # timeline update above share one timestamp and either could count as the latest.
    page.get_by_role('button', name='Rehearsal:', exact=False).click()
    sheet(page).get_by_role('button', name='Move clock +5 min', exact=True).click()
    expect(page.get_by_text('The rehearsal clock moved 5 minutes.')).to_be_visible()
    sheet(page).get_by_role('button', name='Close', exact=True).click()
    tab(page, 'Crew')
    page.get_by_role('button', name='Send update', exact=False).click()
    sheet(page).get_by_role('checkbox', name='Ushers', exact=True).check()
    sheet(page).get_by_label('Message', exact=False).fill('Ceremony moves indoors to the Cedar Ballroom.')
    sheet(page).get_by_role('button', name='Send update', exact=True).click()
    expect(page.get_by_text('Sent to Ushers.')).to_be_visible()

    switch_to(page, 'Jamie Lim')
    expect(page.locator('.update').first).to_be_visible()
    page.screenshot(path=str(out / 'mobile-helper-home.png'))
    tab(page, 'My jobs')
    announcement = page.locator('.update', has_text='Ceremony moves indoors')
    announcement.get_by_role('button', name='Read', exact=True).click()
    expect(page.get_by_text('Marked as read', exact=False)).to_be_visible()
    expect(announcement).to_have_count(0)
    tab(page, 'Home')
    page.locator('.hero').get_by_role('button', name='Got it', exact=True).click()
    expect(page.locator('.hero').get_by_role('button', name='Done', exact=True)).to_be_visible()
    assert page.get_by_role('navigation', name='Sections').get_by_role('button', name='Review', exact=False).count() == 0

    switch_to(page, 'Alex Morgan')
    tab(page, 'Crew')
    expect(page.locator('.stat', has_text='Read update')).to_contain_text('1')

    # A helper reports a problem; it reaches the coordinator's Review.
    switch_to(page, 'Sam Koh')
    home_tile(page, 'Report a problem')
    sheet(page).get_by_label('What is the problem?', exact=False).fill('Bridal car has a flat tyre')
    sheet(page).get_by_role('radio', name='Urgent', exact=True).check()
    sheet(page).get_by_role('button', name='Send report', exact=True).click()
    expect(page.get_by_text('Sent. The coordinator has it.')).to_be_visible()
    switch_to(page, 'Alex Morgan')
    expect(page.locator('.alert-bar')).to_contain_text('Bridal car has a flat tyre')

    # Registration finds a guest's table and confirms arrival in a sheet. No dietary notes.
    switch_to(page, 'Michelle Chen')
    tab(page, 'Guests')
    page.get_by_label('Guest name', exact=True).fill('Sarah Tan')
    expect(page.get_by_role('button', name='Sarah Tan', exact=False)).to_be_visible()
    expect(page.get_by_text('Table 18 · Cedar Ballroom', exact=True)).to_be_visible()
    assert page.get_by_label('Show dietary notes').count() == 0
    page.screenshot(path=str(out / 'mobile-guests.png'))

    # Usher searches the approved venue notes.
    switch_to(page, 'Jamie Lim')
    home_tile(page, 'Venue notes')
    page.get_by_label('Search venue notes').fill('service lift')
    expect(page.get_by_text('The service lift is in the east staff corridor, behind the banquet service door.', exact=True)).to_be_visible()
    home_tile(page, 'Places')
    assert page.get_by_role('button', name='Family contacts', exact=True).count() == 0

    # Coordinator gives a guest a family role and a private phone in a sheet.
    switch_to(page, 'Alex Morgan')
    tab(page, 'Guests')
    page.get_by_label('Guest name', exact=True).fill('Sarah Tan')
    page.get_by_role('button', name='Sarah Tan', exact=False).click()
    sheet(page).get_by_role('button', name='Edit details', exact=True).click()
    sheet(page).get_by_label('Family role', exact=False).fill('sister_of_bride')
    sheet(page).get_by_label('Private phone', exact=False).fill('DEMO-NOT-ROUTABLE-SARAH')
    sheet(page).get_by_role('button', name='Save', exact=True).click()
    expect(page.get_by_text('Guest details saved.')).to_be_visible()

    # Only the family liaison sees the private family contacts.
    switch_to(page, 'Priya Rao')
    home_tile(page, 'Places')
    page.get_by_role('button', name='Family contacts', exact=True).click()
    expect(sheet(page).get_by_text('DEMO-NOT-ROUTABLE-SARAH', exact=False)).to_be_visible()
    sheet(page).get_by_role('button', name='Close', exact=True).click()

    no_overflow(page, 'final screen')
    assert not errors, errors
    report = {
        'mode': 'offline Chromium + in-process ASGI app via request routing (not network E2E)' if args.bridge else 'Chromium HTTP browser E2E',
        'viewport': PHONE,
        'tested_workflows': ['coordinator home hub, tabs and sections', 'helper delay report and coordinator approval sheet',
                             'send update and read status', 'helper got it on next job', 'problem report reaches coordinator',
                             'guest seating lookup without dietary notes', 'venue notes search',
                             'guest family role edit', 'family-contact role visibility', 'no horizontal overflow at phone width'],
        'javascript_errors': errors,
        'screenshots': sorted(str(x.relative_to(root)) for x in out.glob('mobile-*.png')),
    }
    (out / 'browser-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    browser.close()
