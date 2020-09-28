# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _

class PosOrder(models.Model):
    _inherit = 'pos.order'

    def create_picking(self):
        for config in self.mapped('config_id'):
            if config.picking_al_cerrar:
                return True
            else:
                return super(PosOrder, self).create_picking()
