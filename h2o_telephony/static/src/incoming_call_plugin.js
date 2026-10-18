import { onWillDestroy, Plugin, usePlugin } from "@odoo/owl";
import { BusPlugin } from "@bus/services/bus_plugin";
import { _t } from "@web/core/l10n/translation";
import { NotificationPlugin } from "@web/core/notifications/notification_plugin";
import { services } from "@web/core/services";
import { ActionPlugin } from "@web/webclient/actions/action_plugin";

/**
 * Shows dispatchers who is calling the office line, with a button to open
 * the customer (or the call when the number is unknown).
 */
export class IncomingCallPlugin extends Plugin {
    bus = usePlugin(BusPlugin);
    notification = usePlugin(NotificationPlugin);
    action = usePlugin(ActionPlugin);

    setup() {
        const unsubscribe = this.bus.subscribe("h2o_telephony/incoming_call", (payload) =>
            this.notify(payload)
        );
        this.bus.start();

        onWillDestroy(unsubscribe);
    }

    notify({ call_id, number, name, partner_id }) {
        const [resModel, resId, buttonName] = partner_id
            ? ["res.partner", partner_id, _t("Open customer")]
            : ["h2o.call", call_id, _t("Open call")];
        const close = this.notification.add(name ? `${name} (${number})` : number, {
            title: _t("Incoming call"),
            type: "info",
            autocloseDelay: 30000,
            buttons: [
                {
                    name: buttonName,
                    primary: true,
                    onClick: () => {
                        close();
                        this.action.doAction({
                            type: "ir.actions.act_window",
                            res_model: resModel,
                            res_id: resId,
                            views: [[false, "form"]],
                        });
                    },
                },
            ],
        });
    }
}

services.add(IncomingCallPlugin);
