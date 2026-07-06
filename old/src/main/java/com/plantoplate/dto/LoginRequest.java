package com.plantoplate.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

public record LoginRequest(
        @NotBlank @Size(min = 1, message = "Username is required") String username,
        @NotBlank @Size(min = 4, message = "Password must be at least 4 characters") String password
) {
}
