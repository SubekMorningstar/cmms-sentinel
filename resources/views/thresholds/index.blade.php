@extends('layouts.app')

@section('title', 'Threshold Sensor')

@section('breadcrumbs')
    @include('partials.breadcrumb', ['items' => ['Threshold Sensor' => null]])
@endsection

@section('content')
    <div class="row">
        <div class="col">
            <div class="alert alert-info" role="status">
                <i class="ti-info-alt"></i>
                <span>Form pengaturan batas sensor akan terhubung ke data mesin setelah modul data master
                    tersedia.</span>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-lg-8">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-settings"></i> Batas Maksimal Sensor</div>
                    <div class="tools"><span class="badge badge-pill badge-soft">Belum aktif</span></div>
                </div>
                <div class="card-body">
                    <div class="form-group">
                        <label for="mesin">Mesin</label>
                        <select id="mesin" class="form-control" disabled>
                            <option>Belum ada mesin terdaftar</option>
                        </select>
                    </div>

                    <div class="form-row">
                        <div class="col-md-6">
                            <div class="form-group">
                                <label for="max_suhu">Maks. Suhu (°C)</label>
                                <input type="number" id="max_suhu" class="form-control" placeholder="75" disabled>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="form-group">
                                <label for="max_getaran">Maks. Getaran (mm/s)</label>
                                <input type="number" id="max_getaran" class="form-control" placeholder="4.5" disabled>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="form-group">
                                <label for="max_daya">Maks. Daya (kW)</label>
                                <input type="number" id="max_daya" class="form-control" placeholder="15" disabled>
                            </div>
                        </div>
                        <div class="col-md-6">
                            <div class="form-group">
                                <label for="max_suara">Maks. Suara (dB(A))</label>
                                <input type="number" id="max_suara" class="form-control" placeholder="85" disabled>
                            </div>
                        </div>
                    </div>

                    <button type="button" class="btn btn-outline-secondary" disabled>
                        <i class="ti-lock"></i> Simpan Threshold
                    </button>
                    <small class="text-secondary d-block mt-2">Form dapat disimpan setelah mesin dan threshold awal
                        tersedia.</small>
                </div>
            </div>
        </div>
        <div class="col-lg-4">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-info-alt"></i> Catatan</div>
                </div>
                <div class="card-body text-secondary">
                    <p class="mb-2">Satu mesin memiliki satu set threshold. Nilai ini menjadi acuan evaluasi data
                        sensor.</p>
                    <p class="mb-0">Ketika salah satu nilai melewati batas, sistem akan membuat Work Order otomatis.</p>
                </div>
            </div>
        </div>
    </div>
@endsection
