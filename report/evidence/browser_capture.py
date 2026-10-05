import json, time
from pathlib import Path
from playwright.sync_api import sync_playwright
root = Path('report/evidence')
with sync_playwright() as p:
    browser = p.chromium.launch(channel='msedge', headless=False, args=['--start-maximized'])
    page = browser.new_page(no_viewport=True)
    page.goto('http://localhost:7474', wait_until='domcontentloaded')
    page.get_by_label('Database user', exact=True).fill('neo4j')
    from dotenv import dotenv_values
    page.get_by_label('Password', exact=True).fill(dotenv_values('.env').get('NEO4J_PASSWORD','password123'))
    page.get_by_role('button', name='Connect', exact=True).click()
    while True:
        command = root / 'browser_command.json'
        if not command.exists():
            page.wait_for_timeout(300)
            continue
        task = json.loads(command.read_text(encoding='utf-8-sig'))
        command.unlink()
        try:
            action = task['action']
            if action == 'stop': break
            if action == 'inspect':
                result = page.locator('body').inner_text()
                result += '\nINPUTS\n' + str(page.locator('input,textarea,button,[contenteditable]').evaluate_all('(els)=>els.map(e=>({tag:e.tagName,type:e.type,placeholder:e.placeholder,text:e.innerText,aria:e.getAttribute("aria-label")}))'))
            elif action == 'fill':
                page.locator(task['selector']).fill(task['text']); result = 'filled'
            elif action == 'click':
                page.get_by_role(task.get('role','button'), name=task['name'], exact=True).click(); result = 'clicked'
            elif action == 'press':
                page.locator(task['selector']).press(task['key']); result = 'pressed'
            elif action == 'login':
                from dotenv import dotenv_values
                env = dotenv_values('.env')
                page.locator('input[type=password]').fill(env.get('NEO4J_PASSWORD','password123'))
                result = 'password filled from env'
            elif action == 'shot':
                page.screenshot(path=task['path']); result = 'captured viewport'
            page.wait_for_timeout(1200)
            (root/'browser_result.txt').write_text(result, encoding='utf-8')
        except Exception as e:
            (root/'browser_result.txt').write_text(str(e), encoding='utf-8')
    browser.close()

