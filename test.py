import xmlrpc.client

"""url = "https://newkhatulistiwa-staging-first-31289894.dev.odoo.com"
db = "newkhatulistiwa-staging-first-31289894"
username = "robi@nk.com"
password = "451facc87146554709d832136997c11bdb36ba08"

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
db = "falinwasales-fwa-nk18-main-16841291"
username = "robi@nk.com"
password = "7c368acbc801625daf127181a9382deb34547b69"

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