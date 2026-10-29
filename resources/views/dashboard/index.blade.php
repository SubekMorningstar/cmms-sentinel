@extends('layouts.app')

@section('title', 'Dashboard')

@section('breadcrumbs')
    @include('partials.breadcrumb', ['items' => []])
@endsection

@section('content')
    <div class="row">
        <div class="col-lg-8">
            <div class="card mb-3">
                <div class="card-body py-4">
                    <div class="d-flex welcome-row">
                        <span class="welcome-icon"><i class="ti-dashboard"></i></span>
                        <div class="ml-3 welcome-copy">
                            <h4 class="mb-1">Selamat datang, {{ auth()->user()->nama_lengkap }}</h4>
                            <p class="text-secondary mb-0">
                                Fondasi CMMS sudah siap. KPI operasional, peringatan sensor, dan work order otomatis
                                akan tampil di sini setelah data mesin dan gateway IoT terhubung.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
        <div class="col-lg-4">
            <div class="card mb-3">
                <div class="card-body">
                    <div class="d-flex justify-content-between align-items-start">
                        <div>
                            <h6 class="text-secondary bold mb-1">Koneksi Database</h6>
                            <h4 class="mb-1 {{ $databaseStatus === 'Terhubung' ? 'text-success' : 'text-danger' }}">
                                {{ $databaseStatus }}
                            </h4>
                            <small class="text-secondary">MongoDB &middot; {{ $databaseName }}</small>
                        </div>
                        <span class="module-icon"><i class="ti-server"></i></span>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-6 col-xl-3">
            <a href="{{ route('cbm.index') }}" class="card mb-3 quick-link">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <span class="module-icon mr-3"><i class="ti-pulse"></i></span>
                        <div>
                            <h6 class="mb-1">Condition Monitoring</h6>
                            <p class="text-secondary small mb-0">4 kanal sensor</p>
                        </div>
                    </div>
                </div>
            </a>
        </div>
        <div class="col-6 col-xl-3">
            <a href="{{ route('work-orders.index') }}" class="card mb-3 quick-link">
                <div class="card-body">
                    <div class="d-flex align-items-center">
                        <span class="module-icon mr-3"><i class="ti-clipboard"></i></span>
                        <div>
                            <h6 class="mb-1">Work Orders</h6>
                            <p class="text-secondary small mb-0">Tugas perawatan</p>
                        </div>
                    </div>
                </div>
            </a>
        </div>
        @if (auth()->user()->isAdmin())
            <div class="col-6 col-xl-3">
                <a href="{{ route('assets.index') }}" class="card mb-3 quick-link">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <span class="module-icon mr-3"><i class="ti-harddrives"></i></span>
                            <div>
                                <h6 class="mb-1">Assets / Mesin</h6>
                                <p class="text-secondary small mb-0">Master data mesin</p>
                            </div>
                        </div>
                    </div>
                </a>
            </div>
            <div class="col-6 col-xl-3">
                <a href="{{ route('thresholds.index') }}" class="card mb-3 quick-link">
                    <div class="card-body">
                        <div class="d-flex align-items-center">
                            <span class="module-icon mr-3"><i class="ti-settings"></i></span>
                            <div>
                                <h6 class="mb-1">Threshold Sensor</h6>
                                <p class="text-secondary small mb-0">Batas aman sensor</p>
                            </div>
                        </div>
                    </div>
                </a>
            </div>
        @endif
    </div>

    <div class="row">
        <div class="col-lg-7">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-check-box"></i> Kesiapan Sistem</div>
                    <div class="tools"><span class="badge badge-pill badge-soft-success">Siap</span></div>
                </div>
                <div class="card-body">
                    <ul class="list-unstyled setup-checklist mb-0">
                        <li><i class="ti-check text-success"></i> Laravel {{ app()->version() }} + Blade terpasang</li>
                        <li><i class="ti-check text-success"></i> Layout siQtheme &amp; ApexCharts terintegrasi</li>
                        <li><i class="ti-check text-success"></i> Koneksi MongoDB: {{ $databaseStatus }}</li>
                        <li><i class="ti-check text-success"></i> Autentikasi, session, dan role admin/teknisi aktif</li>
                    </ul>
                </div>
            </div>
        </div>
        <div class="col-lg-5">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-flag-alt"></i> Modul Berikutnya</div>
                </div>
                <div class="card-body">
                    <p class="text-secondary mb-2">Data master yang akan disiapkan:</p>
                    <ul class="mb-0 pl-3 text-secondary">
                        <li>Profil mesin dan status operasional</li>
                        <li>Batas aman empat kanal sensor</li>
                        <li>Riwayat pembacaan sensor (time-series)</li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
@endsection
