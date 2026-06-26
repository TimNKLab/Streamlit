import os
import xmlrpc.client


url = os.environ.get("ODOO_HOST", "http://newkhatulistiwa.odoo.com")
db = os.environ.get("ODOO_DATABASE", "")
username = os.environ.get("ODOO_USERNAME", "robi@nk.com")
password = os.environ.get("ODOO_API_KEY", "")

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