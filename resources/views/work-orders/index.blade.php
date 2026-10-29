@extends('layouts.app')

@section('title', 'Work Orders')

@section('breadcrumbs')
    @include('partials.breadcrumb', ['items' => ['Work Orders' => null]])
@endsection

@section('content')
    <div class="row">
        <div class="col">
            <div class="alert alert-info" role="status">
                <i class="ti-info-alt"></i>
                <span>Tabel manajemen Work Order dan perubahan status (pending, progress, resolved) akan aktif setelah
                    modul monitoring sensor berjalan.</span>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-md-12">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-clipboard"></i> Daftar Work Order</div>
                    <div class="tools">
                        <span class="badge badge-pill badge-soft-warning">0 pending</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-bordered table-hover mb-0">
                            <caption class="sr-only">Daftar work order</caption>
                            <thead>
                                <tr>
                                    <th scope="col">WO</th>
                                    <th scope="col">Mesin</th>
                                    <th scope="col">Pemicu</th>
                                    <th scope="col">Teknisi</th>
                                    <th scope="col">Status</th>
                                    <th scope="col">Waktu Dibuat</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td colspan="6" class="empty-row">
                                        <i class="ti-clipboard" aria-hidden="true"></i>
                                        <span class="d-block">Belum ada Work Order</span>
                                        <small class="text-secondary">WO dibuat otomatis saat sensor melewati
                                            threshold.</small>
                                    </td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>
    </div>
@endsection
