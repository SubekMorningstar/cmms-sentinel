<?php

use Illuminate\Database\Migrations\Migration;
use Illuminate\Support\Facades\Schema;
use MongoDB\Laravel\Schema\Blueprint;

return new class extends Migration
{
    protected $connection = 'mongodb';

    public function up(): void
    {
        Schema::create('users', function (Blueprint $collection) {
            $collection->unique('email');
            $collection->index('role');
        });
    }

    public function down(): void
    {
        Schema::drop('users');
    }
};
