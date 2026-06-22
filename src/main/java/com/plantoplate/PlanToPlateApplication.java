package com.plantoplate;

import com.plantoplate.service.UserService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Main entry point for the PlanToPlate Spring Boot 3.x application.
 * 
 * Configuration:
 * - Java 21 LTS runtime (virtual threads enabled via application.yml)
 * - SQLite embedded database in WAL (Write-Ahead Logging) mode
 * - Hibernate with automatic schema update tracking
 */
@SpringBootApplication
public class PlanToPlateApplication {

    @Autowired
    private UserService userService;

    public static void main(String[] args) {
        SpringApplication.run(PlanToPlateApplication.class, args);
    }

    /**
     * Seeds default admin user on application startup if none exists.
     */
    @Autowired(required = false)
    public void seedAdminUser(UserService userService) {
        if (userService != null) {
            userService.createAdminUser();
        }
    }
}
