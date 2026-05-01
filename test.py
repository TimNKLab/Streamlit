import xmlrpc.client

"""url = "https://REDACTED.dev.odoo.com"
db = "REDACTED"
username = "robi@nk.com"
password = "REDACTED"

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, password, {})

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

partners = models.execute_kw(
    db, uid, password,
    'res.partner', 'search_read',
    [[]],
    {'limit': 5}
)

print(partners)"""

url = "http://newkhatulistiwa.odoo.com"
db = "REDACTED"
username = "robi@nk.com"
password = "REDACTED"

common = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/common")
uid = common.authenticate(db, username, password, {})

models = xmlrpc.client.ServerProxy(f"{url}/xmlrpc/2/object")

partners = models.execute_kw(
    db, uid, password,
    'res.partner', 'search_read',
    [[['id', '>', 0]]],   # force match everything
    {
        'fields': ['id', 'name'],
        'limit': 5
    }
)

print("RESULT:", partners)