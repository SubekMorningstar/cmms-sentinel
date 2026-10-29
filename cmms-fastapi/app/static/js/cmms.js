/* =========================================================================
   CMMS Sentinel — interactive layer
   Theme-aware charts, live telemetry, filters, forms & feedback.
   ========================================================================= */
(function () {
    'use strict';

    var reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    var numberFormat = new Intl.NumberFormat('id-ID', { minimumFractionDigits: 1, maximumFractionDigits: 1 });
    var integerFormat = new Intl.NumberFormat('id-ID', { maximumFractionDigits: 0 });
    var chartData = {};
    var charts = [];
    var liveTimer = null;
    var liveBusy = false;

    var SENSOR_LABELS = {
        temperature: 'Suhu',
        vibration: 'Getaran',
        power: 'Daya',
        sound: 'Suara'
    };

    var STATE_LABELS = {
        normal: 'Normal',
        good: 'Baik',
        warning: 'Peringatan',
        critical: 'Kritis',
        unknown: 'Tanpa data'
    };

    var WO_LABELS = {
        pending: 'Menunggu',
        in_progress: 'Dikerjakan',
        resolved: 'Selesai',
        cancelled: 'Dibatalkan'
    };

    function $(selector, root) {
        return (root || document).querySelector(selector);
    }

    function $$(selector, root) {
        return Array.prototype.slice.call((root || document).querySelectorAll(selector));
    }

    function on(root, eventName, selector, handler) {
        if (!root) {
            return;
        }
        root.addEventListener(eventName, function (event) {
            var target = event.target.closest(selector);
            if (target && root.contains(target)) {
                handler.call(target, event);
            }
        });
    }

    function cssValue(name) {
        return getComputedStyle(document.body).getPropertyValue(name).trim();
    }

    function tokens() {
        return {
            dark: false,
            accent: cssValue('--app-accent'),
            accentSoft: cssValue('--ui-accent-soft'),
            good: cssValue('--ui-good'),
            warning: cssValue('--ui-warning'),
            danger: cssValue('--ui-danger'),
            info: cssValue('--ui-info'),
            neutral: cssValue('--ui-neutral'),
            card: cssValue('--app-card-bg'),
            surface: cssValue('--ui-surface-muted'),
            label: cssValue('--ui-chart-label'),
            grid: cssValue('--ui-grid-line'),
            line: cssValue('--ui-line'),
            fontFamily: getComputedStyle(document.body).fontFamily,
            sensors: {
                temperature: cssValue('--sensor-temperature'),
                vibration: cssValue('--sensor-vibration'),
                power: cssValue('--sensor-power'),
                sound: cssValue('--sensor-sound')
            }
        };
    }

    function formatNumber(value, decimals) {
        if (value === null || value === undefined || value === '') {
            return '—';
        }
        var number = Number(value);
        if (!isFinite(number)) {
            return '—';
        }
        var digits = decimals === undefined ? 1 : decimals;
        return new Intl.NumberFormat('id-ID', {
            minimumFractionDigits: digits,
            maximumFractionDigits: digits
        }).format(number);
    }

    function formatCompact(value) {
        if (value === null || value === undefined) {
            return '—';
        }
        var number = Number(value);
        if (!isFinite(number)) {
            return '—';
        }
        return new Intl.NumberFormat('id-ID', { notation: 'compact', maximumFractionDigits: 1 }).format(number);
    }

    function formatDateTime(value) {
        if (!value) {
            return '—';
        }
        var date = new Date(value);
        if (isNaN(date.getTime())) {
            return '—';
        }
        return new Intl.DateTimeFormat('id-ID', {
            day: '2-digit',
            month: 'short',
            year: 'numeric',
            hour: '2-digit',
            minute: '2-digit'
        }).format(date);
    }

    function timeLabel(timestamp) {
        var date = new Date(timestamp);
        if (isNaN(date.getTime())) {
            return '';
        }
        return new Intl.DateTimeFormat('id-ID', {
            hour: '2-digit',
            minute: '2-digit'
        }).format(date);
    }

    function sensorAxis(timestamps) {
        var list = timestamps || [];
        var stride = Math.max(1, Math.ceil(list.length / 5));
        var axis = { categories: [], short: {}, shown: {} };
        for (var index = 0; index < list.length; index += 1) {
            var full = formatDateTime(list[index]);
            axis.categories.push(full);
            axis.short[full] = timeLabel(list[index]);
            if (index % stride === 0) {
                axis.shown[full] = true;
            }
        }
        if (list.length) {
            axis.shown[axis.categories[list.length - 1]] = true;
        }
        return axis;
    }

    function sensorLabelFormatter(axis) {
        return function (value) {
            return axis.shown[value] ? axis.short[value] : '';
        };
    }

    function toast(message, tone) {
        var stack = $('#toast-stack');
        if (!stack) {
            return;
        }
        var item = document.createElement('div');
        var kind = tone || 'success';
        item.className = 'toast' + (kind === 'success' ? '' : ' is-' + kind);
        item.setAttribute('role', kind === 'error' ? 'alert' : 'status');

        var icon = document.createElement('i');
        icon.className = 'toast-icon ' + (kind === 'error' ? 'ti-alert' : kind === 'info' ? 'ti-info-alt' : 'ti-check-box');
        icon.setAttribute('aria-hidden', 'true');

        var text = document.createElement('span');
        text.className = 'toast-message';
        text.textContent = message;

        var close = document.createElement('button');
        close.type = 'button';
        close.className = 'toast-close';
        close.setAttribute('aria-label', 'Tutup notifikasi');
        close.innerHTML = '<i class="ti-close" aria-hidden="true"></i>';
        close.addEventListener('click', function () {
            dismissToast(item);
        });

        item.appendChild(icon);
        item.appendChild(text);
        item.appendChild(close);
        stack.appendChild(item);

        window.setTimeout(function () {
            dismissToast(item);
        }, 5200);
    }

    function dismissToast(item) {
        if (!item || item.classList.contains('is-leaving')) {
            return;
        }
        item.classList.add('is-leaving');
        window.setTimeout(function () {
            item.remove();
        }, 220);
    }

    function showChartEmpty(element, message) {
        element.innerHTML = '';
        var wrapper = document.createElement('div');
        wrapper.className = 'chart-empty';
        var icon = document.createElement('i');
        icon.className = 'ti-bar-chart';
        icon.setAttribute('aria-hidden', 'true');
        var text = document.createElement('span');
        text.textContent = message || 'Belum ada data untuk ditampilkan.';
        wrapper.appendChild(icon);
        wrapper.appendChild(text);
        element.appendChild(wrapper);
    }

    function readChartData() {
        $$('[data-chart-data]').forEach(function (script) {
            try {
                chartData[script.dataset.chartData || 'page'] = JSON.parse(script.textContent);
            } catch (error) {
                chartData[script.dataset.chartData || 'page'] = {};
            }
        });
    }

    function payloadFor(element) {
        var key = element.dataset.chartSource || 'page';
        if (chartData[key]) {
            return chartData[key];
        }
        var keys = Object.keys(chartData);
        return keys.length ? chartData[keys[0]] : {};
    }

    function baseOptions(height, theme) {
        return {
            chart: {
                height: height,
                background: 'transparent',
                fontFamily: theme.fontFamily,
                foreColor: theme.label,
                toolbar: { show: false },
                zoom: { enabled: false },
                animations: {
                    enabled: !reducedMotion,
                    easing: 'easeinout',
                    speed: 650,
                    animateGradually: { enabled: !reducedMotion, delay: 110 },
                    dynamicAnimation: { enabled: !reducedMotion, speed: 360 }
                }
            },
            theme: { mode: theme.dark ? 'dark' : 'light' },
            dataLabels: { enabled: false },
            grid: {
                borderColor: theme.grid,
                strokeDashArray: 4,
                padding: { top: 0, right: 8, bottom: 0, left: 4 }
            },
            tooltip: {
                theme: theme.dark ? 'dark' : 'light',
                shared: true,
                intersect: false
            },
            legend: { show: false },
            noData: { text: 'Belum ada data' }
        };
    }

    function axisLabels(theme) {
        return {
            style: {
                colors: theme.label,
                fontSize: '12px',
                fontFamily: theme.fontFamily
            }
        };
    }

    function buildDashboardTrend(element, payload, theme) {
        var trend = payload.trend || {};
        if (!trend.labels || !trend.labels.length) {
            showChartEmpty(element, 'Belum ada pembacaan sensor 24 jam terakhir.');
            return null;
        }
        var height = parseInt(element.dataset.height, 10) || 270;
        var options = baseOptions(height, theme);
        var sensors = [
            { key: 'temperature', name: 'Suhu (°C)', unit: '°C', color: theme.sensors.temperature, minRange: 1 },
            { key: 'vibration', name: 'Getaran (mm/s)', unit: 'mm/s', color: theme.sensors.vibration, minRange: 0.5 },
            { key: 'power', name: 'Daya (kW)', unit: 'kW', color: theme.sensors.power, minRange: 1 },
            { key: 'sound', name: 'Suara (dB(A))', unit: 'dB(A)', color: theme.sensors.sound, minRange: 5 }
        ];
        options.series = sensors.map(function (sensor) {
            var actual = trend[sensor.key] || [];
            var values = actual.filter(function (value) {
                return typeof value === 'number' && isFinite(value);
            });
            if (!values.length) {
                return { name: sensor.name, data: actual.map(function () { return null; }) };
            }
            var lowest = Math.min.apply(null, values);
            var highest = Math.max.apply(null, values);
            var range = highest - lowest;
            if (!range) {
                range = sensor.minRange;
            }
            var padding = range * 0.1;
            var center = (lowest + highest) / 2;
            var domainMin = center - range / 2 - padding;
            var domainMax = center + range / 2 + padding;
            var laneCenter = 87.5 - sensors.indexOf(sensor) * 25;
            var laneMin = laneCenter - 9;
            var laneMax = laneCenter + 9;
            return {
                name: sensor.name,
                data: actual.map(function (value) {
                    if (typeof value !== 'number' || !isFinite(value)) {
                        return null;
                    }
                    return laneMin + ((value - domainMin) / (domainMax - domainMin)) * (laneMax - laneMin);
                })
            };
        });
        options.chart.type = 'line';
        options.colors = sensors.map(function (sensor) { return sensor.color; });
        options.stroke = {
            curve: 'smooth',
            width: 2.4,
            lineCap: 'round',
            colors: options.colors
        };
        options.markers = { size: 0, hover: { size: 4 } };
        options.labels = trend.labels;
        options.xaxis = {
            type: 'category',
            labels: Object.assign({ rotate: 0, hideOverlappingLabels: true }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false },
            tooltip: { enabled: false }
        };
        options.yaxis = {
            min: 0,
            max: 100,
            show: false,
            labels: Object.assign({ formatter: function (value) { return formatNumber(value, 0); } }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.tooltip.y = {
            formatter: function (value, context) {
                var sensor = sensors[context && context.seriesIndex];
                var index = context && context.dataPointIndex;
                var actual = sensor && trend[sensor.key] ? trend[sensor.key][index] : null;
                return formatNumber(actual, 1) + (sensor ? ' ' + sensor.unit : '');
            }
        };
        return new ApexCharts(element, options);
    }

    function buildAlertMix(element, payload, theme) {
        var breakdown = payload.alert_breakdown || {};
        var sensors = Object.keys(breakdown);
        if (!sensors.length) {
            showChartEmpty(element, 'Tidak ada alert aktif saat ini.');
            return null;
        }
        var warning = [];
        var critical = [];
        var total = 0;
        sensors.forEach(function (sensor) {
            var row = breakdown[sensor] || {};
            warning.push(Number(row.warning) || 0);
            critical.push(Number(row.critical) || 0);
            total += (Number(row.warning) || 0) + (Number(row.critical) || 0);
        });
        if (!total) {
            showChartEmpty(element, 'Tidak ada alert aktif saat ini.');
            return null;
        }
        var height = parseInt(element.dataset.height, 10) || 210;
        var options = baseOptions(height, theme);
        options.series = [
            { name: 'Peringatan', data: warning },
            { name: 'Kritis', data: critical }
        ];
        options.chart.type = 'bar';
        options.chart.stacked = true;
        options.colors = [theme.warning, theme.danger];
        options.plotOptions = {
            bar: {
                horizontal: true,
                barHeight: '52%',
                borderRadius: 3,
                borderRadiusApplication: 'end'
            }
        };
        options.xaxis = {
            categories: sensors.map(function (sensor) { return SENSOR_LABELS[sensor] || sensor; }),
            labels: Object.assign({ formatter: function (value) { return integerFormat.format(value || 0); } }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.yaxis = {
            labels: axisLabels(theme),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.legend = {
            show: true,
            position: 'top',
            horizontalAlign: 'left',
            fontSize: '12px',
            labels: { colors: theme.label },
            markers: { radius: 3 }
        };
        options.tooltip.y = { formatter: function (value) { return integerFormat.format(value || 0) + ' alert'; } };
        return new ApexCharts(element, options);
    }

    function donutOptions(element, labels, values, colors, totalLabel, theme) {
        var sum = values.reduce(function (accumulator, value) { return accumulator + (Number(value) || 0); }, 0);
        if (!sum) {
            showChartEmpty(element, 'Belum ada data untuk ditampilkan.');
            return null;
        }
        var height = parseInt(element.dataset.height, 10) || 230;
        var options = baseOptions(height, theme);
        options.chart.type = 'donut';
        options.series = values;
        options.labels = labels;
        options.colors = colors;
        options.stroke = { width: 3, colors: [theme.card] };
        options.plotOptions = {
            pie: {
                donut: {
                    size: '70%',
                    labels: {
                        show: true,
                        name: { show: false },
                        value: {
                            show: true,
                            fontSize: '1.55rem',
                            fontWeight: 700,
                            color: cssValue('--app-heading'),
                            formatter: function (value) { return integerFormat.format(Number(value) || 0); }
                        },
                        total: {
                            show: true,
                            showAlways: true,
                            label: totalLabel,
                            fontSize: '12px',
                            color: theme.label,
                            formatter: function (w) {
                                return integerFormat.format(w.globals.seriesTotals.reduce(function (a, b) { return a + b; }, 0));
                            }
                        }
                    }
                }
            }
        };
        options.legend = {
            show: true,
            position: 'bottom',
            horizontalAlign: 'center',
            fontSize: '12px',
            itemMargin: { horizontal: 7, vertical: 3 },
            labels: { colors: theme.label },
            markers: { radius: 3 }
        };
        options.tooltip.y = { formatter: function (value) { return integerFormat.format(Number(value) || 0); } };
        return new ApexCharts(element, options);
    }

    function buildWorkOrderMix(element, payload, theme) {
        var breakdown = payload.wo_breakdown || {};
        var keys = ['pending', 'in_progress', 'resolved', 'cancelled'];
        return donutOptions(
            element,
            keys.map(function (key) { return WO_LABELS[key]; }),
            keys.map(function (key) { return Number(breakdown[key]) || 0; }),
            [theme.warning, theme.info, theme.good, theme.neutral],
            'Work Order',
            theme
        );
    }

    function buildHealthMix(element, payload, theme) {
        var states = (payload.kpis && payload.kpis.states) || payload.health_states || {};
        var keys = ['good', 'warning', 'critical', 'unknown'];
        var labels = ['Baik', 'Perhatian', 'Kritis', 'Tanpa data'];
        return donutOptions(
            element,
            labels,
            keys.map(function (key) { return Number(states[key]) || 0; }),
            [theme.good, theme.warning, theme.danger, theme.neutral],
            'Mesin',
            theme
        );
    }

    function sensorSeriesPayload(payload, sensor) {
        var series = payload.series || {};
        return {
            values: series[sensor] || [],
            timestamps: series.timestamps || [],
            threshold: (payload.thresholds && payload.thresholds[sensor]) || {}
        };
    }

    function buildSensorChart(element, payload, theme, sensor) {
        var data = sensorSeriesPayload(payload, sensor);
        if (!data.values.length) {
            showChartEmpty(element, 'Belum ada pembacaan pada rentang waktu ini.');
            return null;
        }
        var meta = (payload.sensor_meta && payload.sensor_meta[sensor]) || {};
        var color = theme.sensors[sensor] || theme.accent;
        var height = parseInt(element.dataset.height, 10) || 200;
        var options = baseOptions(height, theme);
        options.chart.type = 'area';
        options.chart.stacked = false;
        options.series = [{ name: meta.label || SENSOR_LABELS[sensor], data: data.values }];
        options.colors = [color];
        options.stroke = { curve: 'smooth', width: 2.2, lineCap: 'round' };
        options.fill = {
            type: 'gradient',
            gradient: {
                shadeIntensity: 1,
                opacityFrom: theme.dark ? 0.34 : 0.30,
                opacityTo: 0.01,
                stops: [0, 94]
            }
        };
        var axis = sensorAxis(data.timestamps);
        options.xaxis = {
            type: 'category',
            categories: axis.categories,
            labels: Object.assign({
                rotate: 0,
                hideOverlappingLabels: true,
                formatter: sensorLabelFormatter(axis)
            }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false },
            tooltip: { enabled: false }
        };
        options.yaxis = {
            labels: Object.assign({ formatter: function (value) { return formatNumber(value, 0); } }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false },
            forceNiceScale: true,
            title: {
                text: meta.unit || '',
                style: { color: theme.label, fontSize: '12px', fontWeight: 500 }
            }
        };
        var annotations = [];
        if (data.threshold.warning !== null && data.threshold.warning !== undefined) {
            annotations.push({
                y: Number(data.threshold.warning),
                borderColor: theme.warning,
                strokeDashArray: 4,
                label: {
                    text: 'Peringatan ' + formatNumber(data.threshold.warning, 1),
                    position: 'right',
                    textAnchor: 'start',
                    borderWidth: 0,
                    style: { background: 'transparent', color: theme.warning, fontSize: '12px' }
                }
            });
        }
        if (data.threshold.critical !== null && data.threshold.critical !== undefined) {
            annotations.push({
                y: Number(data.threshold.critical),
                borderColor: theme.danger,
                strokeDashArray: 4,
                label: {
                    text: 'Kritis ' + formatNumber(data.threshold.critical, 1),
                    position: 'right',
                    textAnchor: 'start',
                    borderWidth: 0,
                    style: { background: 'transparent', color: theme.danger, fontSize: '12px' }
                }
            });
        }
        if (annotations.length) {
            options.annotations = { yaxis: annotations };
        }
        options.tooltip.y = { formatter: function (value) { return formatNumber(value, 1) + ' ' + (meta.unit || ''); } };
        options.tooltip.x = {
            show: true,
            formatter: function (value, opts) {
                var index = opts && typeof opts.dataPointIndex === 'number' ? opts.dataPointIndex : -1;
                return axis.categories[index] || value || '';
            }
        };
        options.grid.padding = { top: 8, right: 30, bottom: 0, left: 4 };
        var chart = new ApexCharts(element, options);
        chart.__cmmsSensor = sensor;
        return chart;
    }

    function buildReportTrend(element, payload, theme) {
        var trend = payload.wo_trend || {};
        if (!trend.labels || !trend.labels.length) {
            showChartEmpty(element, 'Belum ada riwayat work order pada periode ini.');
            return null;
        }
        var height = parseInt(element.dataset.height, 10) || 280;
        var options = baseOptions(height, theme);
        options.chart.type = 'bar';
        options.series = [
            { name: 'Dibuat', data: trend.created || [] },
            { name: 'Selesai', data: trend.resolved || [] }
        ];
        options.colors = [theme.info, theme.good];
        options.plotOptions = {
            bar: { horizontal: false, columnWidth: '52%', borderRadius: 3, borderRadiusApplication: 'end' }
        };
        options.xaxis = {
            categories: trend.labels,
            labels: Object.assign({ rotate: 0, hideOverlappingLabels: true }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.yaxis = {
            labels: Object.assign({ formatter: function (value) { return integerFormat.format(value || 0); } }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false },
            forceNiceScale: true
        };
        options.legend = {
            show: true,
            position: 'top',
            horizontalAlign: 'right',
            fontSize: '12px',
            labels: { colors: theme.label },
            markers: { radius: 3 }
        };
        options.tooltip.y = { formatter: function (value) { return integerFormat.format(value || 0) + ' WO'; } };
        return new ApexCharts(element, options);
    }

    function buildReportHealth(element, payload, theme) {
        var rows = payload.health || [];
        if (!rows.length) {
            showChartEmpty(element, 'Belum ada skor kesehatan mesin.');
            return null;
        }
        var height = parseInt(element.dataset.height, 10) || 280;
        var options = baseOptions(height, theme);
        options.chart.type = 'bar';
        options.series = [{
            name: 'Skor kesehatan',
            data: rows.map(function (row) { return Number(row.score) || 0; })
        }];
        options.colors = rows.map(function (row) {
            var score = Number(row.score);
            if (!isFinite(score) || !row.score) {
                return theme.neutral;
            }
            if (score >= 85) {
                return theme.good;
            }
            if (score >= 65) {
                return theme.warning;
            }
            return theme.danger;
        });
        options.plotOptions = {
            bar: { horizontal: true, distributed: true, barHeight: '58%', borderRadius: 3, borderRadiusApplication: 'end' }
        };
        options.xaxis = {
            categories: rows.map(function (row) { return row.code; }),
            min: 0,
            max: 100,
            labels: Object.assign({ formatter: function (value) { return integerFormat.format(value) + '%'; } }, axisLabels(theme)),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.yaxis = {
            labels: axisLabels(theme),
            axisBorder: { show: false },
            axisTicks: { show: false }
        };
        options.legend = { show: false };
        options.tooltip.y = { formatter: function (value, opts) { return formatNumber(value, 1) + '/100 · ' + ((rows[opts.dataPointIndex] || {}).health || ''); } };
        return new ApexCharts(element, options);
    }

    function createChart(element) {
        if (!window.ApexCharts) {
            showChartEmpty(element, 'Pustaka grafik tidak tersedia.');
            return null;
        }
        var type = element.dataset.chart;
        var payload = payloadFor(element);
        var theme = tokens();
        var sensor = element.dataset.sensor || 'temperature';
        try {
            if (type === 'dashboard-trend' || type === 'monitor-trend') {
                return buildDashboardTrend(element, payload, theme);
            }
            if (type === 'alert-mix') {
                return buildAlertMix(element, payload, theme);
            }
            if (type === 'wo-mix') {
                return buildWorkOrderMix(element, payload, theme);
            }
            if (type === 'health-mix') {
                return buildHealthMix(element, payload, theme);
            }
            if (type === 'sensor-series') {
                return buildSensorChart(element, payload, theme, sensor);
            }
            if (type === 'report-trend') {
                return buildReportTrend(element, payload, theme);
            }
            if (type === 'report-health') {
                return buildReportHealth(element, payload, theme);
            }
        } catch (error) {
            showChartEmpty(element, 'Grafik tidak dapat ditampilkan pada browser ini.');
            return null;
        }
        return null;
    }

    function initCharts() {
        $$('[data-chart]').forEach(function (element) {
            var instance = createChart(element);
            if (instance) {
                instance.render();
                charts.push({
                    element: element,
                    instance: instance,
                    sensor: element.dataset.sensor || null
                });
            }
        });
    }

    function rebuildCharts() {
        charts.forEach(function (entry) {
            try {
                entry.instance.destroy();
            } catch (error) {
                // Chart may already be detached.
            }
            var replacement = createChart(entry.element);
            if (replacement) {
                replacement.render();
                entry.instance = replacement;
            }
        });
    }

    function updateSensorCharts(payload) {
        if (!charts.length || !payload || !payload.series) {
            return;
        }
        charts.forEach(function (entry) {
            if (!entry.sensor || !entry.instance) {
                return;
            }
            var values = payload.series[entry.sensor];
            if (!values || !values.length) {
                return;
            }
            var timestamps = payload.series.timestamps || [];
            var axis = sensorAxis(timestamps);
            var theme = tokens();
            try {
                entry.instance.updateOptions({
                    xaxis: {
                        categories: axis.categories,
                        labels: Object.assign({
                            rotate: 0,
                            hideOverlappingLabels: true,
                            formatter: sensorLabelFormatter(axis)
                        }, axisLabels(theme)),
                        tooltip: { enabled: false }
                    },
                    tooltip: {
                        x: {
                            show: true,
                            formatter: function (value, opts) {
                                var index = opts && typeof opts.dataPointIndex === 'number' ? opts.dataPointIndex : -1;
                                return axis.categories[index] || value || '';
                            }
                        }
                    }
                }, false, false);
                entry.instance.updateSeries([{
                    name: (payload.sensor_meta && payload.sensor_meta[entry.sensor] ? payload.sensor_meta[entry.sensor].label : SENSOR_LABELS[entry.sensor]),
                    data: values
                }]);
            } catch (error) {
                // Keep the existing render if a live update fails.
            }
        });
    }

    function initLiveMonitor() {
        var root = $('[data-live-monitor]');
        if (!root) {
            return;
        }
        var code = root.dataset.machineCode;
        var hours = root.dataset.hours || '24';
        if (!code) {
            return;
        }
        var indicator = $('[data-live-indicator]', root);
        var updated = $('[data-live-updated]', root);

        function setIndicator(online, message) {
            if (!indicator) {
                return;
            }
            indicator.classList.toggle('is-offline', !online);
            var label = $('[data-live-indicator-text]', indicator);
            if (label && message) {
                label.textContent = message;
            }
        }

        function setStatePill(element, state, customLabel) {
            if (!element) {
                return;
            }
            var normalized = state || 'unknown';
            element.className = 'state-pill is-' + normalized;
            element.textContent = customLabel || STATE_LABELS[normalized] || normalized;
        }

        function applySnapshot(machine, payload) {
            $$('[data-live-value]', root).forEach(function (element) {
                var sensor = element.dataset.liveValue;
                var value = machine.sensors && machine.sensors[sensor] ? machine.sensors[sensor].value : null;
                element.textContent = value === null || value === undefined ? '—' : formatNumber(value, 1);
            });
            $$('[data-live-critical]', root).forEach(function (element) {
                var sensor = element.dataset.liveCritical;
                var sensorData = machine.sensors && machine.sensors[sensor] ? machine.sensors[sensor] : {};
                element.textContent = sensorData.critical === null || sensorData.critical === undefined
                    ? '—'
                    : formatNumber(sensorData.critical, 1);
            });
            $$('[data-live-state]', root).forEach(function (element) {
                var sensor = element.dataset.liveState;
                var sensorData = machine.sensors && machine.sensors[sensor] ? machine.sensors[sensor] : {};
                setStatePill(element, sensorData.state || 'unknown');
            });
            $$('[data-live-reading-time]', root).forEach(function (element) {
                element.textContent = machine.last_reading ? formatDateTime(machine.last_reading) : '—';
            });

            var ring = $('[data-live-health-ring]', root);
            if (ring && machine.health) {
                var score = machine.health.score;
                var healthState = machine.health.state || 'unknown';
                ring.classList.remove('is-good', 'is-warning', 'is-critical', 'is-unknown');
                ring.classList.add('is-' + healthState);
                ring.style.setProperty('--ring-value', isFinite(Number(score)) ? Number(score) : 0);
                var scoreElement = $('[data-live-health-score]', ring);
                if (scoreElement) {
                    scoreElement.textContent = score === null || score === undefined ? '—' : formatNumber(score, 0);
                }
                var healthLabel = $('[data-live-health-label]', root);
                if (healthLabel) {
                    healthLabel.textContent = machine.health.label || '—';
                }
            }

            var onlinePill = $('[data-live-online]', root);
            if (onlinePill) {
                onlinePill.className = machine.online ? 'state-pill is-good is-live' : 'state-pill is-critical';
                onlinePill.textContent = machine.online ? 'Online' : 'Offline';
            }

            var alertCount = $('[data-live-alert-count]', root);
            if (alertCount) {
                alertCount.textContent = integerFormat.format(machine.active_alerts || 0);
            }
            var woCount = $('[data-live-wo-count]', root);
            if (woCount) {
                woCount.textContent = integerFormat.format(machine.open_work_orders || 0);
            }

            if (payload && payload.series) {
                $$('[data-live-chart-value]', root).forEach(function (element) {
                    var sensor = element.dataset.liveChartValue;
                    var values = payload.series[sensor] || [];
                    var latest = null;
                    for (var index = values.length - 1; index >= 0; index -= 1) {
                        if (values[index] !== null && values[index] !== undefined) {
                            latest = values[index];
                            break;
                        }
                    }
                    element.textContent = latest === null ? '—' : formatNumber(latest, 1);
                });
            }

            if (updated) {
                updated.textContent = formatDateTime(payload && payload.generated_at ? payload.generated_at : new Date().toISOString());
            }
            root.setAttribute('aria-busy', 'false');
        }

        function tick() {
            if (liveBusy || document.hidden) {
                return;
            }
            liveBusy = true;
            var url = '/api/machines/' + encodeURIComponent(code) + '/latest?hours=' + encodeURIComponent(hours);
            fetch(url, {
                headers: { 'Accept': 'application/json' },
                credentials: 'same-origin',
                cache: 'no-store'
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error('Telemetry request failed');
                    }
                    return response.json();
                })
                .then(function (payload) {
                    if (!payload || !payload.machine) {
                        throw new Error('Telemetry payload invalid');
                    }
                    applySnapshot(payload.machine, payload);
                    updateSensorCharts(payload);
                    setIndicator(true, 'Telemetry aktif · pembaruan otomatis');
                })
                .catch(function () {
                    setIndicator(false, 'Telemetry terputus · mencoba lagi');
                })
                .finally(function () {
                    liveBusy = false;
                });
        }

        if (document.hidden) {
            setIndicator(false, 'Menunggu tab aktif');
        }
        liveTimer = window.setInterval(tick, 20000);
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) {
                tick();
            }
        });
    }

    function initThresholdPreviews() {
        $$('[data-threshold-card]').forEach(function (card) {
            var sensor = card.dataset.sensor;
            var wrap = card.closest('[data-threshold-form]') || document;
            var warningInput = wrap.querySelector('input[name="' + sensor + '_warning"]');
            var criticalInput = wrap.querySelector('input[name="' + sensor + '_critical"]');
            var preview = $('[data-threshold-preview]', card);
            if (!warningInput || !criticalInput || !preview) {
                return;
            }
            var value = parseFloat(card.dataset.current);
            var warningMarker = $('[data-threshold-warning]', preview);
            var criticalMarker = $('[data-threshold-critical]', preview);
            var valueMarker = $('[data-threshold-value]', preview);
            var rangeLabel = $('[data-threshold-range]', card);

            function update() {
                var warning = parseFloat(String(warningInput.value).replace(',', '.'));
                var critical = parseFloat(String(criticalInput.value).replace(',', '.'));
                if (!isFinite(warning) || !isFinite(critical) || critical <= 0) {
                    return;
                }
                var scale = Math.max(critical * 1.2, warning * 1.2, 0.001);
                var warningPct = Math.min(Math.max(warning / scale * 100, 0), 100);
                var criticalPct = Math.min(Math.max(critical / scale * 100, 0), 100);
                if (warningMarker) {
                    warningMarker.style.left = warningPct + '%';
                }
                if (criticalMarker) {
                    criticalMarker.style.left = criticalPct + '%';
                }
                if (valueMarker && isFinite(value)) {
                    valueMarker.style.left = Math.min(Math.max(value / scale * 100, 0), 100) + '%';
                }
                if (rangeLabel) {
                    rangeLabel.textContent = 'Skala 0 – ' + formatNumber(scale, 1);
                }
            }

            warningInput.addEventListener('input', update);
            criticalInput.addEventListener('input', update);
            update();
        });
    }

    function initCounters() {
        if (reducedMotion) {
            return;
        }
        $$('[data-countup]').forEach(function (element) {
            var target = parseFloat(element.dataset.countup);
            if (!isFinite(target)) {
                return;
            }
            var decimals = parseInt(element.dataset.countupDecimals, 10);
            var digits = isFinite(decimals) ? decimals : 0;
            var duration = 620;
            var started = null;

            function step(timestamp) {
                if (started === null) {
                    started = timestamp;
                }
                var progress = Math.min((timestamp - started) / duration, 1);
                var eased = 1 - Math.pow(1 - progress, 3);
                var current = target * eased;
                element.textContent = digits > 0 ? formatNumber(current, digits) : integerFormat.format(Math.round(current));
                if (progress < 1) {
                    window.requestAnimationFrame(step);
                } else {
                    element.textContent = digits > 0 ? formatNumber(target, digits) : integerFormat.format(Math.round(target));
                }
            }

            element.textContent = digits > 0 ? formatNumber(0, digits) : '0';
            window.requestAnimationFrame(step);
        });
    }

    function initFlashes() {
        $$('.flash').forEach(function (flash) {
            var timer = null;
            var autoHide = flash.dataset.autohide === 'true';
            var close = $('.flash-close', flash);

            function dismiss() {
                if (flash.classList.contains('is-leaving')) {
                    return;
                }
                flash.classList.add('is-leaving');
                window.setTimeout(function () {
                    flash.remove();
                }, 220);
            }

            if (close) {
                close.addEventListener('click', dismiss);
            }
            if (autoHide) {
                timer = window.setTimeout(dismiss, 8000);
                flash.addEventListener('mouseenter', function () {
                    window.clearTimeout(timer);
                });
                flash.addEventListener('mouseleave', function () {
                    timer = window.setTimeout(dismiss, 3200);
                });
                flash.addEventListener('focusin', function () {
                    window.clearTimeout(timer);
                });
            }
        });
    }

    function copyText(text) {
        if (navigator.clipboard && window.isSecureContext) {
            return navigator.clipboard.writeText(text);
        }
        return new Promise(function (resolve, reject) {
            var area = document.createElement('textarea');
            area.value = text;
            area.setAttribute('readonly', 'readonly');
            area.style.position = 'fixed';
            area.style.opacity = '0';
            document.body.appendChild(area);
            area.select();
            try {
                var success = document.execCommand('copy');
                document.body.removeChild(area);
                success ? resolve() : reject(new Error('Copy failed'));
            } catch (error) {
                document.body.removeChild(area);
                reject(error);
            }
        });
    }

    function initCopyButtons() {
        on(document, 'click', '[data-copy-text], [data-copy-target]', function (event) {
            event.preventDefault();
            var text = '';
            if (this.dataset.copyText) {
                text = this.dataset.copyText;
            } else if (this.dataset.copyTarget) {
                var target = $(this.dataset.copyTarget);
                text = target ? (target.textContent || '').trim() : '';
            }
            if (!text) {
                return;
            }
            var button = this;
            copyText(text)
                .then(function () {
                    button.classList.add('copied');
                    window.setTimeout(function () {
                        button.classList.remove('copied');
                    }, 1800);
                    toast(button.dataset.copyLabel || 'Disalin ke clipboard.');
                })
                .catch(function () {
                    toast('Tidak dapat menyalin. Pilih teks lalu salin secara manual.', 'error');
                });
        });
    }

    function initPasswordToggles() {
        on(document, 'click', '[data-toggle-password]', function () {
            var input = $(this.dataset.togglePassword);
            if (!input) {
                return;
            }
            var visible = input.type === 'text';
            input.type = visible ? 'password' : 'text';
            this.setAttribute('aria-pressed', visible ? 'false' : 'true');
            this.setAttribute('aria-label', visible ? 'Tampilkan password' : 'Sembunyikan password');
            var icon = this.querySelector('i');
            if (icon) {
                icon.className = visible ? 'ti-eye' : 'ti-lock';
            }
            input.focus();
        });
    }

    function initDemoFill() {
        on(document, 'click', '[data-demo-fill]', function () {
            var email = $('#email');
            var password = $('#password');
            if (!email || !password) {
                return;
            }
            email.value = this.dataset.email || '';
            password.value = this.dataset.password || '';
            email.dispatchEvent(new Event('input', { bubbles: true }));
            password.dispatchEvent(new Event('input', { bubbles: true }));
            password.focus();
            toast('Akun demo diisi. Tekan "Masuk ke aplikasi".', 'info');
        });
    }

    function initAutoSubmit() {
        $$('[data-auto-submit]').forEach(function (control) {
            control.addEventListener('change', function () {
                var form = control.closest('form');
                if (!form) {
                    return;
                }
                if (typeof form.requestSubmit === 'function') {
                    form.requestSubmit();
                } else {
                    form.submit();
                }
            });
        });
    }

    function initHistoryBack() {
        on(document, 'click', '[data-history-back]', function (event) {
            event.preventDefault();
            if (window.history.length > 1) {
                window.history.back();
            } else {
                window.location.href = '/dashboard';
            }
        });
    }

    function initConfirmations() {
        document.addEventListener('click', function (event) {
            var trigger = event.target.closest('[data-confirm]');
            if (!trigger) {
                return;
            }
            if (!window.confirm(trigger.dataset.confirm)) {
                event.preventDefault();
                event.stopImmediatePropagation();
            }
        }, true);

        document.addEventListener('submit', function (event) {
            var form = event.target;
            if (form.dataset && form.dataset.confirm && !form.dataset.confirmed) {
                if (!window.confirm(form.dataset.confirm)) {
                    event.preventDefault();
                    event.stopImmediatePropagation();
                } else {
                    form.dataset.confirmed = 'true';
                }
            }
        }, true);
    }

    function initRowLinks() {
        on(document, 'click', '[data-row-href]', function (event) {
            if (event.target.closest('a, button, input, select, textarea, label, form')) {
                return;
            }
            window.location.href = this.dataset.rowHref;
        });
        on(document, 'keydown', '[data-row-href]', function (event) {
            if (event.key === 'Enter' || event.key === ' ') {
                if (event.target.closest('a, button, input, select, textarea, label, form')) {
                    return;
                }
                event.preventDefault();
                window.location.href = this.dataset.rowHref;
            }
        });
    }

    function initDueToggle() {
        $$('[data-due-select]').forEach(function (select) {
            var form = select.closest('form');
            var panel = form ? $('[data-due-custom]', form) : null;
            if (!panel) {
                return;
            }
            function update() {
                var show = select.value === 'custom';
                panel.classList.toggle('is-visible', show);
                var input = panel.querySelector('input');
                if (input) {
                    input.required = show;
                    if (show) {
                        input.focus();
                    }
                }
            }
            select.addEventListener('change', update);
            update();
        });
    }

    function initStatusForms() {
        $$('[data-wo-transition]').forEach(function (form) {
            var select = $('[data-status-select]', form);
            var resolvePanel = $('[data-resolve-panel]', form);
            var note = $('[data-transition-note]', form);
            if (!select) {
                return;
            }
            function update() {
                var resolved = select.value === 'resolved';
                var cancelled = select.value === 'cancelled';
                if (resolvePanel) {
                    resolvePanel.classList.toggle('is-visible', resolved);
                }
                if (note) {
                    note.required = resolved || cancelled;
                    if (resolved || cancelled) {
                        note.setAttribute('aria-required', 'true');
                    } else {
                        note.removeAttribute('aria-required');
                    }
                }
                var downtime = resolvePanel ? resolvePanel.querySelector('input[name="downtime_hours"]') : null;
                if (downtime) {
                    downtime.disabled = !resolved;
                }
            }
            select.addEventListener('change', update);
            update();
        });
    }

    function initSubmitGuards() {
        $$('form[data-submit-once]').forEach(function (form) {
            form.addEventListener('submit', function () {
                window.setTimeout(function () {
                    $$('button[type="submit"], input[type="submit"]', form).forEach(function (button) {
                        button.disabled = true;
                        button.setAttribute('aria-disabled', 'true');
                    });
                    form.setAttribute('aria-busy', 'true');
                }, 0);
            });
        });
        window.addEventListener('pageshow', function () {
            $$('form[data-submit-once][aria-busy="true"]').forEach(function (form) {
                form.removeAttribute('aria-busy');
                $$('button[type="submit"], input[type="submit"]', form).forEach(function (button) {
                    button.disabled = false;
                    button.removeAttribute('aria-disabled');
                });
            });
        });
    }

    function initTooltips() {
        if (window.jQuery && window.jQuery.fn && window.jQuery.fn.tooltip) {
            window.jQuery('[data-toggle="tooltip"]').tooltip({ container: 'body', trigger: 'hover focus' });
        }
    }

    function init() {
        readChartData();
        initCharts();
        initLiveMonitor();
        initThresholdPreviews();
        initCounters();
        initFlashes();
        initCopyButtons();
        initPasswordToggles();
        initDemoFill();
        initAutoSubmit();
        initHistoryBack();
        initConfirmations();
        initRowLinks();
        initDueToggle();
        initStatusForms();
        initSubmitGuards();
        initTooltips();
    }

    window.CMMSSentinel = {
        toast: toast,
        refreshCharts: rebuildCharts,
        formatNumber: formatNumber
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
