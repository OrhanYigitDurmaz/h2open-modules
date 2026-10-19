import {
    Component,
    onMounted,
    onWillStart,
    onWillUnmount,
    proxy,
    signal,
    useEffect,
    useProps,
} from "@odoo/owl";
import { loadCSS, loadJS } from "@web/core/assets";
import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

const LEAFLET = "/h2o_customer/static/lib/leaflet";
const TURKIYE = { center: [39.0, 35.2], zoom: 6 };
const PIN_ZOOM = 17;

/**
 * Map on the customer form to set the exact location of the address: click
 * the map or drag the pin, search an address (OpenStreetMap), or paste a
 * location or Google Maps link. Writes partner_latitude / partner_longitude.
 */
export class H2oLocationMap extends Component {
    static template = "h2o_customer.LocationMap";
    props = useProps({ ...standardWidgetProps });
    mapRef = signal.ref();

    setup() {
        this.orm = useService("orm");
        this.state = proxy({ query: "", results: [], noResult: false, searching: false });
        this.map = null;
        this.marker = null;

        onWillStart(() =>
            Promise.all([loadJS(`${LEAFLET}/leaflet.js`), loadCSS(`${LEAFLET}/leaflet.css`)])
        );
        onMounted(() => this.createMap());
        onWillUnmount(() => {
            this.resizeObserver?.disconnect();
            this.map?.remove();
        });
        useEffect(() => {
            const point = this.point;
            const readonly = this.props.readonly;
            if (this.map) {
                this.showPoint(point, readonly);
            }
        });
    }

    get point() {
        const { partner_latitude: lat, partner_longitude: lng } = this.props.record.data;
        return lat || lng ? [lat, lng] : null;
    }

    get addressQuery() {
        const data = this.props.record.data;
        return [data.street, data.street2, data.zip, data.city, data.state_id?.display_name]
            .filter(Boolean)
            .join(", ");
    }

    createMap() {
        L.Icon.Default.imagePath = `${LEAFLET}/images/`;
        this.map = L.map(this.mapRef(), { scrollWheelZoom: false });
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
        }).addTo(this.map);
        const point = this.point;
        if (point) {
            this.map.setView(point, PIN_ZOOM);
        } else {
            this.map.setView(TURKIYE.center, TURKIYE.zoom);
        }
        this.map.on("click", (ev) => {
            if (!this.props.readonly) {
                this.setPoint([ev.latlng.lat, ev.latlng.lng]);
            }
        });
        // The map is often in a notebook page that is hidden when it is created.
        this.resizeObserver = new ResizeObserver(() => this.map.invalidateSize());
        this.resizeObserver.observe(this.mapRef());
        this.showPoint(point, this.props.readonly);
    }

    showPoint(point, readonly) {
        if (!point) {
            this.marker?.remove();
            this.marker = null;
            return;
        }
        if (!this.marker) {
            this.marker = L.marker(point, { draggable: true }).addTo(this.map);
            this.marker.on("dragend", () => {
                const { lat, lng } = this.marker.getLatLng();
                this.setPoint([lat, lng]);
            });
        } else {
            this.marker.setLatLng(point);
        }
        if (readonly) {
            this.marker.dragging.disable();
        } else {
            this.marker.dragging.enable();
        }
        if (!this.map.getBounds().contains(point)) {
            this.map.setView(point, Math.max(this.map.getZoom(), PIN_ZOOM));
        }
    }

    setPoint(point) {
        const round = (value) => Math.round(value * 1e7) / 1e7;
        this.props.record.update({
            partner_latitude: point ? round(point[0]) : 0,
            partner_longitude: point ? round(point[1]) : 0,
        });
    }

    async locate(text) {
        if (!text.trim()) {
            return;
        }
        this.state.searching = true;
        this.state.results = [];
        this.state.noResult = false;
        try {
            const found = await this.orm.call("res.partner", "h2o_locate", [text]);
            if (found.point) {
                this.goTo(found.point);
            } else if (found.results.length === 1) {
                this.onPick(found.results[0]);
            } else {
                this.state.results = found.results;
                this.state.noResult = !found.results.length;
            }
        } finally {
            this.state.searching = false;
        }
    }

    goTo(point) {
        this.setPoint(point);
        this.map.setView(point, PIN_ZOOM);
    }

    onKeydown(ev) {
        if (ev.key === "Enter") {
            ev.preventDefault();
            this.locate(this.state.query);
        }
    }

    onSearch() {
        this.locate(this.state.query);
    }

    onSearchAddress() {
        this.state.query = this.addressQuery;
        this.locate(this.state.query);
    }

    onPick(result) {
        this.state.results = [];
        this.goTo([result.lat, result.lng]);
    }

    onClear() {
        this.setPoint(null);
    }
}

export const h2oLocationMap = {
    component: H2oLocationMap,
    fieldDependencies: [
        { name: "partner_latitude", type: "float", string: _t("Latitude"), readonly: false },
        { name: "partner_longitude", type: "float", string: _t("Longitude"), readonly: false },
    ],
};

registry.category("view_widgets").add("h2o_location_map", h2oLocationMap);
