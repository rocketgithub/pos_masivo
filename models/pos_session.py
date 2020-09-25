# -*- encoding: utf-8 -*-

from odoo import models, fields, api, _
from odoo.tools import float_is_zero
from odoo.exceptions import UserError

import logging

class PosSession(models.Model):
    _inherit = 'pos.session'

    order_picking_id = fields.Many2one('stock.picking', string='Albarán Salida', readonly=True, copy=False)
    return_picking_id = fields.Many2one('stock.picking', string='Albarán Devolución', readonly=True, copy=False)
    stock_inventory_id = fields.Many2one('stock.inventory', string='Ajuste de inventario', copy=False, domain="[('state','=','confirm')]")
    proceso_masivo_generado = fields.Boolean(string='Procesado', readonly=True, copy=False)
        
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
            tiene_movimientos = False
            if not session.order_picking_id and not session.return_picking_id:
                logging.warn('pos_masivo: session '+str(session))
                lineas_agrupadas = {}
                for order in session.order_ids.filtered(lambda l: not l.picking_id):
                    if order.picking_id:
                        tiene_movimientos = True
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
                if not lineas or tiene_movimientos:
                    continue

                address = {}
                if 'default_client_id' in session.config_id.fields_get():
                    address = session.config_id.default_client_id.address_get(['delivery'])
                picking_type = session.config_id.picking_type_id
                return_pick_type = session.config_id.picking_type_id.return_picking_type_id or session.config_id.picking_type_id
                order_picking = Picking
                return_picking = Picking
                moves = Move
                location_id = session.config_id.stock_location_id.id
                if 'default_client_id' in session.config_id.fields_get() and session.config_id.default_client_id:
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
                        'cuenta_analitica_id': session.config_id.analytic_account_id.id if ( 'analytic_account_id' in session.config_id.fields_get() and session.config_id.analytic_account_id ) else False,
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
                    session._force_picking_done(return_picking)
                if order_picking:
                    logging.warn('pos_masivo: order_picking '+str(order_picking))
                    session._force_picking_done(order_picking)

                # when the pos.config has no picking_type_id set only the moves will be created
                if moves and not return_picking and not order_picking:
                    moves._action_assign()
                    moves.filtered(lambda m: m.product_id.tracking == 'none')._action_done()

        logging.warn('pos_masivo: return')
        return True
        
    def _force_picking_done(self, picking):
        """Force picking in order to be set as done."""
        self.ensure_one()
        logging.warn('pos_masivo: action_assign')
        picking.action_assign()
        
        for move in picking.move_lines:
            qty_done = move.product_uom_qty
            if not float_is_zero(qty_done, precision_rounding=move.product_uom.rounding):
                if len(move._get_move_lines()) < 2:
                    move.quantity_done = qty_done
                else:
                    move._set_quantity_done(qty_done)

        logging.warn('pos_masivo: action_done')
        picking.action_done()
        
    def _generar_despacho(self, actual=0, total=1):
        logging.warn('pos_masivo: actual {} total {} '.format(actual, total))
        sesiones = self.search([('state','=','closed'), ('proceso_masivo_generado','=',False)], order="stop_at")
        logging.warn('pos_masivo: sesiones pendientes '+str(sesiones))
        sesiones_filtradas = sesiones.filtered(lambda r: r.id % total == actual - 1)
        logging.warn('pos_masivo: sesiones filtradas '+str(sesiones_filtradas))
        if len(sesiones_filtradas) > 0:
            session = sesiones_filtradas[0]

            logging.warn('pos_masivo: intentando session '+str(session))
            if not session.order_picking_id and not session.return_picking_id:
                session.create_picking()
                
            if session.stock_inventory_id and session.stock_inventory_id.state == 'confirm':
                logging.warn('pos_masivo: intentando inventory '+str(session.stock_inventory_id))
                values = session.stock_inventory_id._get_inventory_lines_values()
                for line in session.stock_inventory_id.line_ids:
                    logging.warn('pos_masivo: line.product_id '+str(line.product_id))
                    logging.warn('pos_masivo: line.theoretical_qty '+str(line.theoretical_qty))
                    logging.warn('pos_masivo: line.product_qty '+str(line.product_qty))
                    cantidad_original = line.product_qty
                    for v in values:
                        if line.product_id.id == v['product_id'] and 'product_qty' in v:
                            line.theoretical_qty = v['product_qty']
                    line.product_qty = cantidad_original if cantidad_original > 0 else 0
                    logging.warn('pos_masivo: line.theoretical_qty '+str(line.theoretical_qty))
                    logging.warn('pos_masivo: line.product_qty '+str(line.product_qty))
                
                try:            
                    session.stock_inventory_id.action_validate()
                except UserError:
                    logging.warn('pos_masivo: UserError ')
                
            session.proceso_masivo_generado = True
            logging.warn('pos_masivo: finalizada session '+str(session))

        return True
