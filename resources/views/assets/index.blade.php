@extends('layouts.app')

@section('title', 'Assets / Mesin')

@section('breadcrumbs')
    @include('partials.breadcrumb', ['items' => ['Assets / Mesin' => null]])
@endsection

@section('content')
    <div class="row">
        <div class="col">
            <div class="alert alert-info" role="status">
                <i class="ti-info-alt"></i>
                <span>CRUD data mesin (tambah, ubah, hapus, dan filter status) akan diaktifkan setelah struktur data
                    master disiapkan.</span>
            </div>
        </div>
    </div>

    <div class="row">
        <div class="col-md-12">
            <div class="card mb-3">
                <div class="card-header">
                    <div class="caption"><i class="ti-harddrives"></i> Data Mesin</div>
                    <div class="tools">
                        <span class="badge badge-pill badge-soft">Menunggu data</span>
                    </div>
                </div>
                <div class="card-body">
                    <div class="table-responsive">
                        <table class="table table-bordered table-hover mb-0">
                            <caption class="sr-only">Daftar mesin terdaftar</caption>
                            <thead>
                                <tr>
                                    <th scope="col">Kode Mesin</th>
                                    <th scope="col">Nama Mesin</th>
                                    <th scope="col">Lokasi</th>
                                    <th scope="col">Status Operasional</th>
                                    <th scope="col" class="text-right">Aksi</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr>
                                    <td colspan="5" class="empty-row">
                                        <i class="ti-harddrives" aria-hidden="true"></i>
                                        <span class="d-block">Belum ada mesin terdaftar</span>
                                        <small class="text-secondary">Data master akan tersedia pada tahap berikutnya.</small>
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
