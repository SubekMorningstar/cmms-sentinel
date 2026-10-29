<?php

namespace App\Http\Controllers;

use Illuminate\Support\Facades\DB;
use Illuminate\View\View;
use Throwable;

class DashboardController extends Controller
{
    public function index(): View
    {
        try {
            DB::connection('mongodb')->getMongoDB()->command(['ping' => 1])->toArray();
            $databaseStatus = 'Terhubung';
        } catch (Throwable) {
            $databaseStatus = 'Tidak terhubung';
        }

        return view('dashboard.index', [
            'databaseStatus' => $databaseStatus,
            'databaseName' => config('database.connections.mongodb.database'),
        ]);
    }
}
