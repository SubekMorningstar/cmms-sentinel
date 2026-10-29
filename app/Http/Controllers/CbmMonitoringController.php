<?php

namespace App\Http\Controllers;

use Illuminate\View\View;

class CbmMonitoringController extends Controller
{
    public function index(): View
    {
        return view('cbm.index');
    }
}
