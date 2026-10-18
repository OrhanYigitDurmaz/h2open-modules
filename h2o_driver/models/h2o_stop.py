from collections import defaultdict

from odoo import api, models

# Trip states during which the driver app is told about stop changes.
H2O_TRIP_IN_PROGRESS = ('loaded', 'on_road')


class H2oStop(models.Model):
    _inherit = 'h2o.stop'

    @api.model_create_multi
    def create(self, vals_list):
        stops = super().create(vals_list)
        self._h2o_push_trip_changed(stops._h2o_by_trip_in_progress(), 'added')
        return stops

    def write(self, vals):
        if 'trip_id' not in vals:
            return super().write(vals)
        removed = self.filtered(lambda s: s.trip_id.id != vals['trip_id'])._h2o_by_trip_in_progress()
        res = super().write(vals)
        self._h2o_push_trip_changed(removed, 'removed')
        self._h2o_push_trip_changed(self._h2o_by_trip_in_progress(), 'added')
        return res

    def unlink(self):
        removed = self._h2o_by_trip_in_progress()
        res = super().unlink()
        self._h2o_push_trip_changed(removed, 'removed')
        return res

    def _h2o_by_trip_in_progress(self):
        """``{trip: stop ids}`` for the stops on loaded or started trips."""
        result = defaultdict(list)
        for stop in self.sudo():
            if stop.trip_id.state in H2O_TRIP_IN_PROGRESS and stop.trip_id.driver_id:
                result[stop.trip_id].append(stop.id)
        return result

    @api.model
    def _h2o_push_trip_changed(self, stops_by_trip, change):
        """Tell the driver app to reload the trips that got or lost stops."""
        Device = self.env['h2o.push.device']
        for trip, stop_ids in stops_by_trip.items():
            Device._h2o_send(trip.driver_id, {
                'type': 'trip_changed',
                'trip_id': trip.id,
                'change': change,
                'stop_ids': ','.join(map(str, stop_ids)),
            }, app='driver')
