# -*- encoding: utf-8 -*-

from openerp import models, fields, api, _

class PosConfig(models.Model):
    _inherit = 'pos.config'

    picking_al_cerrar = fields.Boolean(string="Picking al Cerrar Sesión")
