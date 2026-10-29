<?php

namespace App\Http\Controllers;

use Illuminate\View\View;

class ThresholdController extends Controller
{
    public function index(): View
    {
        return view('thresholds.index');
    }
}
