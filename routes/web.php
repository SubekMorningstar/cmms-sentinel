<?php

use App\Http\Controllers\AssetController;
use App\Http\Controllers\AuthController;
use App\Http\Controllers\CbmMonitoringController;
use App\Http\Controllers\DashboardController;
use App\Http\Controllers\ThresholdController;
use App\Http\Controllers\WorkOrderController;
use Illuminate\Support\Facades\Route;

Route::redirect('/', '/dashboard');

Route::middleware('guest')->group(function () {
    Route::get('/login', [AuthController::class, 'create'])->name('login');
    Route::post('/login', [AuthController::class, 'store'])
        ->middleware('throttle:5,1')
        ->name('login.store');
});

Route::middleware('auth')->group(function () {
    Route::get('/dashboard', [DashboardController::class, 'index'])->name('dashboard');
    Route::get('/cbm-monitoring', [CbmMonitoringController::class, 'index'])->name('cbm.index');
    Route::get('/work-orders', [WorkOrderController::class, 'index'])->name('work-orders.index');

    Route::middleware('role:admin')->group(function () {
        Route::get('/assets', [AssetController::class, 'index'])->name('assets.index');
        Route::get('/thresholds', [ThresholdController::class, 'index'])->name('thresholds.index');
    });

    Route::post('/logout', [AuthController::class, 'destroy'])->name('logout');
});
