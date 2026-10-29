<?php

namespace App\Http\Controllers;

use Illuminate\View\View;

class AssetController extends Controller
{
    public function index(): View
    {
        return view('assets.index');
    }
}
