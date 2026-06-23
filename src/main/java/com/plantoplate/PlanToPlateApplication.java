package com.plantoplate;

import org.springframework.boot.CommandLineRunner;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import com.plantoplate.service.UserService;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * Main entry point for the PlanToPlate Spring Boot 3.x application.
 * 
 * Configuration:
 * - Java 21 LTS runtime (virtual threads enabled via application.yml)
 * - SQLite embedded database in WAL (Write-Ahead Logging) mode
 * - Hibernate with automatic schema update tracking
 */
@SpringBootApplication
public class PlanToPlateApplication implements CommandLineRunner {

    @Autowired(required = false)
    private UserService userService;

    @Autowired(required = false)
    private BCryptPasswordEncoder passwordEncoder;

    public static void main(String[] args) {
        SpringApplication.run(PlanToPlateApplication.class, args);
    }

    @Override
    public void run(String... args) {
        if (userService != null && passwordEncoder != null) {
            userService.createAdminUser();
        }
    }
}
