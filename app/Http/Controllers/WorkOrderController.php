<?php

namespace App\Http\Controllers;

use Illuminate\View\View;

class WorkOrderController extends Controller
{
    public function index(): View
    {
        return view('work-orders.index');
    }
}
