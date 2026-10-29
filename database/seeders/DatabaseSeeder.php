<?php

namespace Database\Seeders;

use App\Models\User;
use Illuminate\Database\Seeder;
use Illuminate\Support\Facades\Hash;

class DatabaseSeeder extends Seeder
{
    public function run(): void
    {
        User::updateOrCreate(
            ['email' => 'admin@cmms.test'],
            [
                'nama_lengkap' => 'Administrator',
                'role' => User::ROLE_ADMIN,
                'password' => Hash::make('password'),
            ],
        );

        User::updateOrCreate(
            ['email' => 'teknisi@cmms.test'],
            [
                'nama_lengkap' => 'Budi Santoso',
                'role' => User::ROLE_TEKNISI,
                'password' => Hash::make('password'),
            ],
        );
    }
}
