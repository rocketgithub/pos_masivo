
# -*- coding: utf-8 -*-

{
    'name': 'Point of Sale para muchos movimientos',
    'version': '1.0',
    'category': 'Point of Sale',
    'sequence': 6,
    'summary': 'Para restaurantes o ventas de muchas lineas. Hace más rápida cada venta.',
    'description': """ Para restaurantes o ventas de muchas lineas. Hace más rápida cada venta. """,
    'author': 'Rodrigo Fernandez',
    'depends': ['point_of_sale'],
    'data': [
        'data/pos_masivo_data.xml',
        'views/pos_config_view.xml',
        'views/pos_session_view.xml',
    ],
    'installable': True,
    'website': 'http://aquih.com',
    'auto_install': False,
}

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:
