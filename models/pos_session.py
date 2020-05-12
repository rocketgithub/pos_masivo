# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.tools import float_is_zero
from odoo.exceptions import UserError

import logging

class PosSession(models.Model):
    _inherit = 'pos.session'

    order_picking_id = fields.Many2one('stock.picking', string='Salidas', readonly=True, copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Devoluciones', readonly=True, copy=False)

    def action_pos_session_close(self):
        logging.warn('pos_masivo: action_pos_session_close')
        result = super(PosSession, self).action_pos_session_close()
        self.create_picking()
        return result

    def create_picking(self):
        """Crear solamente un picking por todas las ventas, agrupando las lineas."""
        Order = self.env['pos.order']
        Picking = self.env['stock.picking']
        # If no email is set on the user, the picking creation and validation will fail be cause of
        # the 'Unable to log message, please configure the sender's email address.' error.
        # We disable the tracking in this case.
        if not self.env.user.partner_id.email:
            Picking = Picking.with_context(tracking_disable=True)
        Move = self.env['stock.move']
        StockWarehouse = self.env['stock.warehouse']
        for session in self:
            if not session.order_picking_id and not session.return_picking_id:
                logging.warn('pos_masivo: session '+str(session))
                lineas_agrupadas = {}
                for order in session.order_ids.filtered(lambda l: not l.picking_id):
                    for line in order.lines.filtered(lambda l: l.product_id.type in ['product', 'consu']):
                        tipo = 'salida'
                        if line.qty < 0:
                            tipo = 'devolucion'
                        llave = str(line.product_id.id)+'-'+tipo
                        if llave not in lineas_agrupadas:
                            lineas_agrupadas[llave] = {
                                'name': line.name,
                                'product_id': line.product_id,
                                'qty': line.qty,
                                'state': 'draft',
                            }
                        else:
                            lineas_agrupadas[llave]['qty'] += line.qty

                lineas = list(lineas_agrupadas.values())
                logging.warn('pos_masivo: lineas '+str(lineas))
                if not lineas:
                    continue

                address = session.config_id.default_client_id.address_get(['delivery']) or {}
                picking_type = session.config_id.picking_type_id
                return_pick_type = session.config_id.picking_type_id.return_picking_type_id or session.config_id.picking_type_id
                order_picking = Picking
                return_picking = Picking
                moves = Move
                location_id = session.config_id.stock_location_id.id
                if session.config_id.default_client_id:
                    destination_id = session.config_id.default_client_id.property_stock_customer.id
                else:
                    if (not picking_type) or (not picking_type.default_location_dest_id):
                        customerloc, supplierloc = StockWarehouse._get_partner_locations()
                        destination_id = customerloc.id
                    else:
                        destination_id = picking_type.default_location_dest_id.id

                if picking_type:
                    message = _("This transfer has been created from the point of sale session: <a href=# data-oe-model=pos.session data-oe-id=%d>%s</a>") % (session.id, session.name)
                    picking_vals = {
                        'origin': session.name,
                        'partner_id': address.get('delivery', False),
                        'date_done': session.stop_at,
                        'picking_type_id': picking_type.id,
                        'company_id': session.config_id.company_id.id,
                        'move_type': 'direct',
                        'location_id': location_id,
                        'location_dest_id': destination_id,
                        'cuenta_analitica_id': session.config_id.analytic_account_id.id if session.config_id.analytic_account_id else False,
                    }
                    logging.warn('pos_masivo: picking_vals '+str(picking_vals))
                    pos_qty = any([x['qty'] > 0 for x in lineas if x['product_id'].type in ['product', 'consu']])
                    if pos_qty:
                        order_picking = Picking.create(picking_vals.copy())
                        if self.env.user.partner_id.email:
                            order_picking.message_post(body=message)
                        else:
                            order_picking.sudo().message_post(body=message)
                    neg_qty = any([x['qty'] < 0 for x in lineas if x['product_id'].type in ['product', 'consu']])
                    if neg_qty:
                        return_vals = picking_vals.copy()
                        return_vals.update({
                            'location_id': destination_id,
                            'location_dest_id': return_pick_type != picking_type and return_pick_type.default_location_dest_id.id or location_id,
                            'picking_type_id': return_pick_type.id
                        })
                        return_picking = Picking.create(return_vals)
                        if self.env.user.partner_id.email:
                            return_picking.message_post(body=message)
                        else:
                            return_picking.message_post(body=message)

                for line in [l for l in lineas if not float_is_zero(l['qty'], precision_rounding=l['product_id'].uom_id.rounding)]:
                    moves |= Move.create({
                        'name': line['name'],
                        'product_uom': line['product_id'].uom_id.id,
                        'picking_id': order_picking.id if line['qty'] >= 0 else return_picking.id,
                        'picking_type_id': picking_type.id if line['qty'] >= 0 else return_pick_type.id,
                        'product_id': line['product_id'].id,
                        'product_uom_qty': abs(line['qty']),
                        'state': 'draft',
                        'location_id': location_id if line['qty'] >= 0 else destination_id,
                        'location_dest_id': destination_id if line['qty'] >= 0 else return_pick_type != picking_type and return_pick_type.default_location_dest_id.id or location_id,
                    })
                logging.warn('pos_masivo: moves '+str(moves))

                # prefer associating the regular order picking, not the return
                session.write({'order_picking_id': order_picking.id, 'return_picking_id': return_picking.id})

                if return_picking:
                    logging.warn('pos_masivo: return_picking '+str(return_picking))
                    return_picking.sudo().action_assign()
                    return_picking.sudo().action_done()
                if order_picking:
                    logging.warn('pos_masivo: order_picking '+str(order_picking))
                    order_picking.sudo().action_assign()
                    order_picking.sudo().action_done()

                # when the pos.config has no picking_type_id set only the moves will be created
                if moves and not return_picking and not order_picking:
                    moves._action_assign()
                    moves.filtered(lambda m: m.product_id.tracking == 'none')._action_done()

        logging.warn('pos_masivo: return')
        return True
