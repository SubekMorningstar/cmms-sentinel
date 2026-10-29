@extends('layouts.app')

@section('title', 'Condition Monitoring')

@section('breadcrumbs')
    @include('partials.breadcrumb', ['items' => ['Condition Monitoring' => null]])
@endsection

@section('content')
    @php($sensors = [
        ['label' => 'Suhu', 'unit' => '°C', 'icon' => 'fa-thermometer-half', 'color' => 'text-danger'],
        ['label' => 'Getaran', 'unit' => 'mm/s', 'icon' => 'fa-signal', 'color' => 'text-warning'],
        ['label' => 'Daya', 'unit' => 'kW', 'icon' => 'fa-bolt', 'color' => 'text-info'],
        ['label' => 'Suara', 'unit' => 'dB(A)', 'icon' => 'fa-volume-up', 'color' => 'text-success'],
    ])

    <div class="row">
        <div class="col">
            <div class="card mb-3">
                <div class="card-body">
                    <div class="row align-items-end">
                        <div class="col-md-6">
                            <label for="mesin-select">Pilih Mesin</label>
                            <select id="mesin-select" class="form-control" disabled>
                                <option>Belum ada mesin terdaftar</option>
                            </select>
                            <small class="text-secondary d-block mt-2">Daftar mesin akan tersedia setelah data master
                                diisi.</small>
                        </div>
                        <div class="col-md-6 text-md-right mt-3 mt-md-0">
                            <span class="badge badge-pill badge-soft-warning">
                                <i class="ti-time"></i> Menunggu data
                            </span>
                            <span class="text-secondary small d-block mt-2">Empat grafik real-time akan aktif saat
                                gateway mulai mengirim data.</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col">
            <div class="alert alert-info" role="status">
                <i class="ti-info-alt"></i>
                <span>Kerangka halaman siap. Pemilihan mesin, polling API, dan grafik waktu-nyata akan diaktifkan
                    setelah data sensor tersedia.</span>
            </div>
        </div>
    </div>

    <div class="row">
        @foreach ($sensors as $sensor)
            <div class="col-lg-6">
                <div class="card mb-3">
                    <div class="card-header">
                        <div class="caption">
                            <i class="fa {{ $sensor['icon'] }} {{ $sensor['color'] }}"></i> {{ $sensor['label'] }}
                        </div>
                        <div class="tools"><span class="text-secondary">{{ $sensor['unit'] }}</span></div>
                    </div>
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-baseline mb-2">
                            <h3 class="mb-0 sensor-value">&mdash;</h3>
                            <small class="text-secondary">Belum ada data</small>
                        </div>
                        <div class="chart-placeholder">
                            <i class="ti-bar-chart" aria-hidden="true"></i>
                            <span>Grafik {{ $sensor['label'] }} siap menerima data</span>
                        </div>
                    </div>
                </div>
            </div>
        @endforeach
    </div>
@endsection
