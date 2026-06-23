package com.plantoplate.controller;

import java.util.Map;

import org.springframework.http.ResponseEntity;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/authenticated")
@PreAuthorize("hasAnyRole('USER', 'ADMIN')")
public class AuthenticatedController {

    @GetMapping("/profile")
    public ResponseEntity<?> getProfile() {
        return ResponseEntity.ok(Map.of("message", "Authenticated user profile"));
    }

    @PostMapping("/data")
    public ResponseEntity<?> postData(@RequestBody Object data) {
        return ResponseEntity.ok(Map.of("message", "Received authenticated data"));
    }
}
