<?php

namespace App\Models;

use Illuminate\Notifications\Notifiable;
use MongoDB\Laravel\Auth\User as Authenticatable;

class User extends Authenticatable
{
    use Notifiable;

    public const ROLE_ADMIN = 'admin';

    public const ROLE_TEKNISI = 'teknisi';

    protected $connection = 'mongodb';

    protected $fillable = [
        'nama_lengkap',
        'email',
        'password',
        'role',
    ];

    protected $hidden = [
        'password',
        'remember_token',
    ];

    protected function casts(): array
    {
        return [
            'password' => 'hashed',
        ];
    }

    public function isAdmin(): bool
    {
        return $this->role === self::ROLE_ADMIN;
    }

    public function getRoleLabelAttribute(): string
    {
        return $this->role === self::ROLE_ADMIN ? 'Administrator' : 'Teknisi';
    }

    public function getInitialsAttribute(): string
    {
        $words = preg_split('/\s+/', trim((string) $this->nama_lengkap)) ?: [];

        return strtoupper(substr($words[0] ?? 'U', 0, 1).substr($words[1] ?? '', 0, 1));
    }
}
